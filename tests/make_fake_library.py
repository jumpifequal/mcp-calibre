import sqlite3, zipfile, os, json, pymupdf
from pathlib import Path
root = Path(__file__).resolve().parent / "Calibre Library"; root.mkdir(exist_ok=True)
c = sqlite3.connect(root/"metadata.db")
c.executescript("""
CREATE TABLE books(id INTEGER PRIMARY KEY, title TEXT, sort TEXT, timestamp TEXT, pubdate TEXT, series_index REAL DEFAULT 1.0, author_sort TEXT, path TEXT, has_cover INTEGER DEFAULT 0, uuid TEXT);
CREATE TABLE authors(id INTEGER PRIMARY KEY, name TEXT, sort TEXT, link TEXT DEFAULT '');
CREATE TABLE books_authors_link(id INTEGER PRIMARY KEY, book INTEGER, author INTEGER);
CREATE TABLE tags(id INTEGER PRIMARY KEY, name TEXT);
CREATE TABLE books_tags_link(id INTEGER PRIMARY KEY, book INTEGER, tag INTEGER);
CREATE TABLE series(id INTEGER PRIMARY KEY, name TEXT, sort TEXT);
CREATE TABLE books_series_link(id INTEGER PRIMARY KEY, book INTEGER, series INTEGER);
CREATE TABLE publishers(id INTEGER PRIMARY KEY, name TEXT, sort TEXT);
CREATE TABLE books_publishers_link(id INTEGER PRIMARY KEY, book INTEGER, publisher INTEGER);
CREATE TABLE languages(id INTEGER PRIMARY KEY, lang_code TEXT);
CREATE TABLE books_languages_link(id INTEGER PRIMARY KEY, book INTEGER, lang_code INTEGER, item_order INTEGER DEFAULT 0);
CREATE TABLE ratings(id INTEGER PRIMARY KEY, rating INTEGER);
CREATE TABLE books_ratings_link(id INTEGER PRIMARY KEY, book INTEGER, rating INTEGER);
CREATE TABLE data(id INTEGER PRIMARY KEY, book INTEGER, format TEXT, uncompressed_size INTEGER, name TEXT);
CREATE TABLE comments(id INTEGER PRIMARY KEY, book INTEGER, text TEXT);
CREATE TABLE identifiers(id INTEGER PRIMARY KEY, book INTEGER, type TEXT, val TEXT);
CREATE TABLE annotations(id INTEGER PRIMARY KEY, book INTEGER, format TEXT, user_type TEXT, user TEXT, timestamp REAL, annot_id TEXT, annot_type TEXT, annot_data TEXT, searchable_text TEXT);
""")
c.execute("INSERT INTO books VALUES (1,'Sicurezza delle reti','Sicurezza delle reti','2025-03-01 10:00:00+00:00','2019-05-01 00:00:00+00:00',2,'Rossi, Mario','Mario Rossi/Sicurezza delle reti (1)',1,'u1')")
c.execute("INSERT INTO books VALUES (2,'Practical Malware Analysis','Practical Malware Analysis','2026-01-10 10:00:00+00:00','0101-01-01 00:00:00+00:00',1,'Sikorski, Michael','Michael Sikorski/Practical Malware Analysis (2)',0,'u2')")
c.executemany("INSERT INTO authors VALUES (?,?,?,'')",[(1,'Mario Rossi','Rossi, Mario'),(2,'Michael Sikorski','Sikorski, Michael'),(3,'Andrew Honig','Honig, Andrew')])
c.executemany("INSERT INTO books_authors_link(book,author) VALUES (?,?)",[(1,1),(2,2),(2,3)])
c.executemany("INSERT INTO tags VALUES (?,?)",[(1,'security'),(2,'networking'),(3,'malware')])
c.executemany("INSERT INTO books_tags_link(book,tag) VALUES (?,?)",[(1,1),(1,2),(2,1),(2,3)])
c.execute("INSERT INTO series VALUES (1,'Manuali','Manuali')"); c.execute("INSERT INTO books_series_link(book,series) VALUES (1,1)")
c.execute("INSERT INTO publishers VALUES (1,'No Starch','No Starch')"); c.execute("INSERT INTO books_publishers_link(book,publisher) VALUES (2,1)")
c.executemany("INSERT INTO languages VALUES (?,?)",[(1,'ita'),(2,'eng')]); c.executemany("INSERT INTO books_languages_link(book,lang_code) VALUES (?,?)",[(1,1),(2,2)])
c.execute("INSERT INTO ratings VALUES (1,8)"); c.execute("INSERT INTO books_ratings_link(book,rating) VALUES (2,1)")
c.executemany("INSERT INTO data(book,format,uncompressed_size,name) VALUES (?,?,?,?)",[(1,'EPUB',1000,'Sicurezza delle reti - Mario Rossi'),(2,'PDF',2000,'Practical Malware Analysis - Michael Sikorski')])
c.execute("INSERT INTO comments(book,text) VALUES (1,'<p>Un <b>manuale</b> di sicurezza.</p>')")
c.execute("INSERT INTO identifiers(book,type,val) VALUES (2,'isbn','9781593272906')")
c.execute("INSERT INTO annotations(book,format,user_type,user,timestamp,annot_id,annot_type,annot_data,searchable_text) VALUES (1,'EPUB','local','viewer',1.0,'a1','highlight',?,?)",
  (json.dumps({"highlighted_text":"Il firewall è la prima linea di difesa","notes":"vedi cap 2","toc_family_titles":["Capitolo 1"],"style":{"which":"yellow"}}),"Il firewall è la prima linea di difesa vedi cap 2"))
c.commit()
# EPUB
d1 = root/"Mario Rossi/Sicurezza delle reti (1)"; d1.mkdir(parents=True, exist_ok=True)
ch1 = "<html><body><h1>Capitolo 1</h1><p>Il firewall è la prima linea di difesa perimetrale.</p><script>evil()</script></body></html>"
ch2 = "<html><body><h1>Capitolo 2</h1><p>La segmentazione della rete riduce la superficie d'attacco. Sécurité à l'école.</p></body></html>"
with zipfile.ZipFile(d1/"Sicurezza delle reti - Mario Rossi.epub","w") as z:
    z.writestr("mimetype","application/epub+zip")
    z.writestr("META-INF/container.xml",'<?xml version="1.0"?><container xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles><rootfile full-path="OEBPS/content.opf"/></rootfiles></container>')
    z.writestr("OEBPS/content.opf",'<?xml version="1.0"?><package xmlns="http://www.idpf.org/2007/opf"><manifest><item id="nav" href="nav.xhtml" properties="nav" media-type="application/xhtml+xml"/><item id="c1" href="text/c1.xhtml" media-type="application/xhtml+xml"/><item id="c2" href="text/c2.xhtml" media-type="application/xhtml+xml"/></manifest><spine><itemref idref="c1"/><itemref idref="c2"/></spine></package>')
    z.writestr("OEBPS/nav.xhtml",'<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops"><body><nav epub:type="toc"><ol><li><a href="text/c1.xhtml">Capitolo 1 - Firewall</a><ol><li><a href="text/c2.xhtml#s">Capitolo 2 - Segmentazione</a></li></ol></li></ol></nav></body></html>')
    z.writestr("OEBPS/text/c1.xhtml",ch1); z.writestr("OEBPS/text/c2.xhtml",ch2)
# PDF
d2 = root/"Michael Sikorski/Practical Malware Analysis (2)"; d2.mkdir(parents=True, exist_ok=True)
doc = pymupdf.open()
for i in range(3):
    p = doc.new_page(); p.insert_text((72,72), f"Page {i+1}: dynamic analysis with a sandbox and process hollowing detection.")
doc.set_toc([[1,"Intro",1],[1,"Dynamic analysis",2]]); doc.save(d2/"Practical Malware Analysis - Michael Sikorski.pdf")
# Calibre FTS db (only book 1 extracted -> book 2 tests on-demand PDF path)
f = sqlite3.connect(root/"full-text-search.db")
f.executescript("""CREATE TABLE books_text(id INTEGER PRIMARY KEY, book INTEGER NOT NULL, timestamp REAL NOT NULL, format TEXT NOT NULL COLLATE NOCASE, format_size INTEGER NOT NULL, format_hash TEXT NOT NULL, err_msg TEXT DEFAULT '', searchable_text TEXT NOT NULL DEFAULT '', text_size INTEGER NOT NULL DEFAULT 0, text_hash TEXT NOT NULL DEFAULT '', UNIQUE(book, format));
CREATE TABLE dirtied_formats(id INTEGER PRIMARY KEY, book INTEGER NOT NULL, format TEXT NOT NULL COLLATE NOCASE, in_progress INTEGER NOT NULL DEFAULT FALSE);""")
t = ("Capitolo 1\n\nIl firewall è la prima linea di difesa perimetrale.\n\n" + "Testo di riempimento. "*300 +
     "\n\nCapitolo 2\n\nLa segmentazione della rete riduce la superficie d'attacco. Sécurité à l'école. Il firewall di nuovo.")
f.execute("INSERT INTO books_text VALUES (1,1,0,'EPUB',1000,'h',?,?,?,'th1')",('',t,len(t)))
f.execute("INSERT INTO books_text VALUES (2,2,0,'PDF',2000,'h','pdf error','',0,'')")
f.execute("INSERT INTO dirtied_formats(book,format) VALUES (2,'PDF')")
f.commit(); print("ok")
