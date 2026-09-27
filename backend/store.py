import contextlib
import datetime
import json
import sqlite3
import uuid
from pathlib import Path

def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()

class Store:
    def __init__(self,path):
        self.path=Path(path)
        self.path.parent.mkdir(parents=True,exist_ok=True)
        with self.db() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS objects(id TEXT PRIMARY KEY, kind TEXT NOT NULL, created TEXT NOT NULL, payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
            ''')

    @contextlib.contextmanager
    def db(self):
        db=sqlite3.connect(self.path,timeout=10)
        try:
            with db: yield db
        finally: db.close()

    def add(self,kind,payload):
        item={'id':uuid.uuid4().hex,'kind':kind,'created_at':now(),**payload}
        with self.db() as db:
            db.execute('INSERT INTO objects VALUES(?,?,?,?)',(item['id'],kind,item['created_at'],json.dumps(item,ensure_ascii=False,allow_nan=False)))
        return item

    def add_many(self,kind,payloads,receipt_key):
        items=[{'id':uuid.uuid4().hex,'kind':kind,'created_at':now(),**p} for p in payloads]
        with self.db() as db:
            db.executemany('INSERT INTO objects VALUES(?,?,?,?)',[(x['id'],kind,x['created_at'],json.dumps(x,ensure_ascii=False,allow_nan=False)) for x in items])
            db.execute('INSERT INTO settings VALUES(?,?)',(receipt_key,json.dumps({'entry_ids':[x['id'] for x in items],'already_created':True})))
        return items

    def items(self,kind):
        with self.db() as db:
            return [json.loads(x[0]) for x in db.execute('SELECT payload FROM objects WHERE kind=? ORDER BY created',(kind,))]

    def get(self,id):
        with self.db() as db:
            row=db.execute('SELECT payload FROM objects WHERE id=?',(id,)).fetchone()
        if row is None: raise KeyError('not_found')
        return json.loads(row[0])

    def update(self,id,changes):
        with self.db() as db:
            row=db.execute('SELECT payload FROM objects WHERE id=?',(id,)).fetchone()
            if row is None: raise KeyError('not_found')
            item=json.loads(row[0]);item.update(changes)
            db.execute('UPDATE objects SET payload=? WHERE id=?',(json.dumps(item,ensure_ascii=False,allow_nan=False),id))
        return item

    def delete(self,id):
        with self.db() as db:
            row=db.execute('SELECT payload FROM objects WHERE id=?',(id,)).fetchone()
            target=json.loads(row[0]) if row else {}
            source=target.get('source_text')
            if target.get('kind')=='entry' and source:
                # Sibling drafts can share a transcript. Once one is deleted, discard
                # the full shared transcript in every remaining entry and revision.
                for oid,kind,payload in db.execute('SELECT id,kind,payload FROM objects WHERE kind IN (?,?)',('entry','entry_revision')).fetchall():
                    item=json.loads(payload)
                    obj=item.get('previous',{}) if kind=='entry_revision' else item
                    if obj.get('source_text')==source:
                        obj.pop('source_text',None)
                        db.execute('UPDATE objects SET payload=? WHERE id=?',(json.dumps(item,ensure_ascii=False),oid))
            revisions=[row[0] for row in db.execute('SELECT id,payload FROM objects WHERE kind=?',('entry_revision',)) if json.loads(row[1]).get('entry_id')==id]
            db.executemany('DELETE FROM objects WHERE id=?',[(x,) for x in revisions])
            db.execute('DELETE FROM objects WHERE id=? AND kind IN (?,?,?)',(id,'entry','audio','plan'))

    def setting(self,key,default=None):
        with self.db() as db:
            row=db.execute('SELECT value FROM settings WHERE key=?',(key,)).fetchone()
        return json.loads(row[0]) if row else default

    def set_setting(self,key,value):
        with self.db() as db:
            db.execute('INSERT OR REPLACE INTO settings VALUES(?,?)',(key,json.dumps(value)))
