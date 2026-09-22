"""Run from the server owner's console with the same DATA_DIR as the service."""
from contextlib import closing
from getpass import getpass
import server

if __name__ == '__main__':
    password = getpass('New teacher password (12-256 characters): ')
    if not 12 <= len(password) <= 256:
        raise SystemExit('Password must contain 12-256 characters.')
    if password != getpass('Confirm password: '):
        raise SystemExit('Passwords do not match.')
    with closing(server.connect()) as con, con:
        updated = con.execute("UPDATE config SET value=? WHERE key='password'", (server.password_hash(password),))
        if updated.rowcount != 1:
            raise SystemExit('Existing database not found. Check DATA_DIR.')
        con.execute("DELETE FROM sessions WHERE role='teacher'")
    print('Teacher password updated. Teacher sessions have been signed out.')
