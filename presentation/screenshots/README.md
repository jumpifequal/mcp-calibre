# UX documentation screenshots

`ux-gallery-en.png`, `ux-reader-en.png`, `ux-quotes-en.png` and their `-it` counterparts
are browser captures of the actual [gallery view](../../mcpcalibre/ui/gallery.html), hosted in a
simulated MCP Apps frame. They are not screenshots of a particular chat client.

**The Demo Library** is a fictional demonstration book. Its cover and figures are generated with
Pillow; its sample text is original demonstration content. No real book, author, publisher, personal
library or external image is used. Book text stays in English in both captures to show that changing
the interface language does not translate the source.

Rebuild from the repository root:

```powershell
python presentation/render_ux_demo.py --channel msedge
```

Requires Pillow, Playwright and the selected browser. Use `--channel chrome` for installed Chrome,
or omit `--channel` for Playwright's Chromium. The script generates both languages, checks that the
images and reader have loaded, and rejects JavaScript errors. It does not open a Calibre library.
