import io, queue, sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "gui"))
try:
    import tkinter  # the console module imports Tk at load time
except ImportError:
    print("tkinter not available: console logic tests skipped")
    sys.exit(0)
import calibre_mcp_console as c

clf = c.Classifier()
cases = [
 ("INFO:     127.0.0.1:5 - \"POST /mcp HTTP/1.1\" 200 OK", "request"),
 ("INFO:     127.0.0.1:5 - \"POST /mcp HTTP/1.1\" 401 Unauthorized", "warning"),
 ("INFO:     127.0.0.1:5 - \"POST /mcp HTTP/1.1\" 500 Internal", "error"),
 ("2026-10-05 10:00:00,1 INFO calibre_mcp listening", "status"),
 ("2026-10-05 10:00:00,1 WARNING calibre_mcp OCR needed", "warning"),
 ("2026-10-05 10:00:00,1 ERROR calibre_mcp boom", "error"),
 ("2026-10-05 10:00:00,1 DEBUG q=firewall", "debug"),
 ("INFO indexed 120/980 books", "progress"),
 ("downloading model 42%", "progress"),
 ("started on 2026-10-05", "status"),
 ("Traceback (most recent call last):", "error"),
 ('  File "x.py", line 1, in <module>', "error"),
 ("    1/0", "error"),
 ("ZeroDivisionError: division by zero", "error"),
 ("plain text after traceback", "status"),
 ("2026-10-05T10:00:00.000Z [calibre] [info] Message from client: {\"method\":\"tools/list\"}", "request"),
 ("2026-10-05T10:00:00.000Z [calibre] [error] Server transport closed", "error"),
 ("C:\\x\\a.py:3: DeprecationWarning: old", "warning"),
 ("\x1b[32mINFO\x1b[0m: ready", "status"),
 # lines produced by the real server (level-less format under the HTTP transport)
 ("calibre-mcp 5.3.1: library 'Calibre Library' at /tmp/realdata3/3214f9612ef9 (sidecar /tmp/realdata3/3214f9612ef9)", "status"),
 ("HTTP endpoint http://127.0.0.1:8798/mcp (auth=bearer, allowed hosts=['127.0.0.1:*'])", "status"),
 ("index sync {'added': 1, 'removed': 0, 'seconds': 0.01}", "status"),
 ("StreamableHTTP session manager started", "status"),
 ("Terminating session: None", "request"),
 ("HTTP 401 from 127.0.0.1 /mcp", "warning"),
 ("HTTP 500 from 127.0.0.1 /mcp", "error"),
 ("HTTP auth DISABLED: any local process can query the library", "warning"),
 ("Non-loopback bind WITHOUT TLS: bearer token and book content travel in clear.", "warning"),
 ("index sync failed", "warning"),
 ("done: 39 ok, 1 failed", "status"),
 ('  "failed": 0,', "status"),
 ("{", "status"),
 ("}", "status"),
 ("note: captions indexed for keyword search only (Semantic search backend 'fastembed' unavailable)", "status"),
 ("embedding 27/40 (67%)", "progress"),
 ("book 12/40: indexing", "progress"),
]
bad = 0
for text, want in cases:
    r = clf.classify(text)
    got = r[0] if r else None
    ok = got == want
    bad += not ok
    print(("ok  " if ok else "FAIL"), want.ljust(8), got, "|", text[:60].encode("ascii","replace").decode())
assert clf.classify("") is None

# \r progress + split chunks + multibyte split across reads
class Pipe:
    def __init__(s, chunks): s.ch = list(chunks)
    def read1(s, n): return s.ch.pop(0) if s.ch else b""
q = queue.Queue()
data = "a ✓ 1/4\rb 2/4\rb 3/4\r\nfinal ✓\nWARNING x\n".encode()
chunks = [data[i:i+5] for i in range(0, len(data), 5)]   # cuts multibyte chars
c.pump_stream(Pipe(chunks), "task", "err", q, c.Classifier())
evs = []
while not q.empty(): evs.append(q.get())
for e in evs: print(" ", e.kind, e.replace, repr(e.text))
assert [e.kind for e in evs] == ["progress","progress","progress","status","warning"], [e.kind for e in evs]
assert [e.replace for e in evs][:3] == [True, True, False]
assert evs[3].text == "final ✓"
# capture mode
cap = []; q2 = queue.Queue()
c.pump_stream(Pipe([b'{"a": 1}\n{"b": 2}\n']), "task", "out", q2, c.Classifier(), cap)
assert cap == ['{"a": 1}', '{"b": 2}'] and q2.empty()
print("progress:", c.parse_progress("embedding 3/4"), c.parse_progress("50%"), c.parse_progress("v1.2.3"), c.parse_progress("5/3"))
print("FAILURES:", bad)
sys.exit(1 if bad else 0)
