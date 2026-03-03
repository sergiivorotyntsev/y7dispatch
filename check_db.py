import sqlite3
conn = sqlite3.connect('data/control_panel.db')
tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
for t in sorted(tables):
    try:
        cnt = conn.execute(f'SELECT COUNT(*) FROM [{t}]').fetchone()[0]
        print(f'{t}: {cnt}')
    except:
        pass
