"""Regenerates the project icon set (SVG source -> PNG sizes, favicon.ico, GitHub social preview).

    pip install cairosvg pillow
    python presentation/icon/build_icons.py presentation/icon

The social preview text uses the Carlito font when installed (falls back to DejaVu Sans / sans-serif).
"""
import os, sys
import cairosvg
from PIL import Image

NAVY = '#1b2a3a'
TEAL_S, CREAM_S, AMBER_S = '#1c7c70', '#d9bf80', '#c97d14'

DEFS = '''<defs>
<linearGradient id="bg" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#2a4560"/><stop offset="1" stop-color="#131f2d"/></linearGradient>
<radialGradient id="stage" cx=".5" cy=".45" r=".55"><stop offset="0" stop-color="#3a6285"/><stop offset="1" stop-color="#3a6285" stop-opacity="0"/></radialGradient>
<radialGradient id="teal" cx=".34" cy=".24" r=".95"><stop offset="0" stop-color="#9af0e2"/><stop offset=".36" stop-color="#43bdad"/><stop offset="1" stop-color="#1d8074"/></radialGradient>
<radialGradient id="tealD" cx=".34" cy=".24" r=".95"><stop offset="0" stop-color="#6fd8c8"/><stop offset=".4" stop-color="#2fa496"/><stop offset="1" stop-color="#176a60"/></radialGradient>
<radialGradient id="cream" cx=".36" cy=".26" r=".9"><stop offset="0" stop-color="#ffffff"/><stop offset=".45" stop-color="#fff2d2"/><stop offset="1" stop-color="#e3ca8e"/></radialGradient>
<radialGradient id="amber" cx=".36" cy=".26" r=".9"><stop offset="0" stop-color="#ffe3a8"/><stop offset=".45" stop-color="#ffb84d"/><stop offset="1" stop-color="#df8b1c"/></radialGradient>
<radialGradient id="pupil" cx=".38" cy=".3" r=".9"><stop offset="0" stop-color="#46607a"/><stop offset="1" stop-color="#0e1822"/></radialGradient>
</defs>'''

def el(tag, **a):
    return '<%s %s></%s>' % (tag, ' '.join('%s="%s"' % (k.replace('_', '-'), v) for k, v in a.items()), tag)

def puff(tag, grad, shade, sw=0, depth=7, rot=None, **g):
    common = dict(g, stroke_linejoin='round', stroke_linecap='round')
    under = dict(common, fill=shade)
    base = dict(common, fill='url(#%s)' % grad)
    if sw:
        under.update(stroke=shade, stroke_width=sw)
        base.update(stroke='url(#%s)' % grad, stroke_width=sw)
    under['transform'] = 'translate(0 %s)%s' % (depth, (' rotate(%s)' % rot) if rot else '')
    if rot: base['transform'] = 'rotate(%s)' % rot
    return el(tag, **under) + el(tag, **base)

def hl(cx, cy, rx, ry, rot=0, op=.5):
    return el('ellipse', cx=cx, cy=cy, rx=rx, ry=ry, fill='#fff', opacity=op, transform='rotate(%s %s %s)' % (rot, cx, cy))

def line(d, color, w, op=1):
    return el('path', d=d, fill='none', stroke=color, stroke_width=w, stroke_linecap='round', stroke_linejoin='round', opacity=op)

def owl():
    s = el('ellipse', cx=128, cy=229, rx=66, ry=9, fill='#000', opacity=.28)                     # ground shadow
    s += puff('ellipse', 'amber', AMBER_S, 0, 3, cx=108, cy=221, rx=15, ry=8)                      # feet
    s += puff('ellipse', 'amber', AMBER_S, 0, 3, cx=148, cy=221, rx=15, ry=8)
    s += puff('path', 'teal', TEAL_S, 12, 6, d='M74 88 L82 52 L114 74 Z')                           # ear tufts
    s += puff('path', 'teal', TEAL_S, 12, 6, d='M182 88 L174 52 L142 74 Z')
    s += puff('ellipse', 'tealD', TEAL_S, 0, 5, cx=64, cy=152, rx=15, ry=38, rot='-12 64 152')      # wings
    s += puff('ellipse', 'tealD', TEAL_S, 0, 5, cx=192, cy=152, rx=15, ry=38, rot='12 192 152')
    s += puff('ellipse', 'teal', TEAL_S, 0, 8, cx=128, cy=142, rx=64, ry=70)                        # body
    s += puff('ellipse', 'cream', CREAM_S, 0, 4, cx=128, cy=166, rx=38, ry=42)                      # belly
    for y in (152, 168, 184):
        s += line('M104 %d q6 7 12 0 q6 7 12 0 q6 7 12 0 q6 7 12 0' % y, '#d2b878', 4)
    for cx in (98, 158):                                                                            # glasses + eyes
        s += el('circle', cx=cx, cy=114, r=27, fill=AMBER_S)
        s += el('circle', cx=cx, cy=108, r=27, fill='url(#cream)', stroke='url(#amber)', stroke_width=8)
    s += el('circle', cx=102, cy=111, r=11.5, fill='url(#pupil)') + el('circle', cx=154, cy=111, r=11.5, fill='url(#pupil)')
    s += el('circle', cx=98, cy=106, r=3.8, fill='#fff') + el('circle', cx=150, cy=106, r=3.8, fill='#fff')
    s += puff('path', 'amber', AMBER_S, 9, 4, d='M118 132 L138 132 L128 148 Z')                     # beak
    s += hl(79, 172, 6, 22, -14, .4) + hl(128, 79, 13, 4, 0, .5) + hl(90, 66, 7, 3, -35, .45) + hl(166, 66, 7, 3, 35, .35)   # gloss, clear of the eyes
    s += hl(116, 158, 12, 5, -15, .7)
    return '<g transform="translate(0 -4)">' + s + '</g>'

def square(px=None):
    size = '' if px is None else ' width="%d" height="%d"' % (px, px)
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256"%s role="img" aria-label="mcp-calibre owl">' % size
            + DEFS + el('rect', width=256, height=256, rx=60, fill='url(#bg)') + el('circle', cx=128, cy=128, r=104, fill='url(#stage)') + owl() + '</svg>')

def transparent():
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256" role="img" aria-label="mcp-calibre owl">' + DEFS + owl() + '</svg>')

def social():
    font = 'font-family="Carlito, DejaVu Sans, sans-serif"'
    chips = ''.join('<rect x="%d" y="462" width="%d" height="52" rx="26" fill="#1d3a4b"/><text x="%d" y="498" fill="#6fd8c8">%s</text>' % (x, w, x + 22, t)
                    for x, w, t in ((650, 168, 'full-text'), (836, 188, 'semantic'), (1042, 108, 'OCR'), (1168, 0, '')) if w)
    return ('<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="640" viewBox="0 0 1280 640">' + DEFS
        + '<defs><linearGradient id="bgs" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#1c2f45"/><stop offset="1" stop-color="#0f1a26"/></linearGradient></defs>'
        + el('rect', width=1280, height=640, fill='url(#bgs)')
        + el('circle', cx=330, cy=320, r=270, fill='url(#stage)')
        + '<g transform="translate(95 70) scale(1.95)">' + owl() + '</g>'
        + '<text x="642" y="296" %s font-weight="700" font-size="112" fill="#fff2d2">mcp-calibre</text>' % font
        + '<text x="648" y="364" %s font-size="38" fill="#9fb4c8">Read-only MCP server</text>' % font
        + '<text x="648" y="412" %s font-size="38" fill="#9fb4c8">for your Calibre library</text>' % font
        + '<g %s font-size="30" font-weight="700">' % font + chips + '</g></svg>')

out = sys.argv[1]
os.makedirs(out, exist_ok=True)
open(out + '/mcp-calibre-owl.svg', 'w').write(square())
open(out + '/mcp-calibre-owl-transparent.svg', 'w').write(transparent())
open(out + '/social-preview.svg', 'w').write(social())
for px in (1024, 512, 256, 128, 64, 32, 16):
    cairosvg.svg2png(bytestring=square().encode(), write_to='%s/mcp-calibre-owl-%d.png' % (out, px), output_width=px, output_height=px)
cairosvg.svg2png(bytestring=transparent().encode(), write_to=out + '/mcp-calibre-owl-transparent-512.png', output_width=512, output_height=512)
cairosvg.svg2png(bytestring=social().encode(), write_to=out + '/social-preview.png', output_width=1280, output_height=640)
big = Image.open(out + '/mcp-calibre-owl-256.png').convert('RGBA')
big.save(out + '/favicon.ico', sizes=[(16, 16), (32, 32), (48, 48), (64, 64)])
print(sorted(os.listdir(out)))
