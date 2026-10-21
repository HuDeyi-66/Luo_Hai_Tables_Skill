"""Reproduce the README's mathematical operator plates (documentation only).

Install requirements-render.txt, then: python docs/assets/operators/render.py
Uses Matplotlib's LaTeX-style MathText with bundled STIX fonts; no TeX service,
runtime Skill import, browser, network, or sibling checkout is required.
"""
from __future__ import annotations

import ast
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
os.environ.setdefault('MPLCONFIGDIR', str(Path(os.environ.get('TEMP', '/tmp')) / 'seaflow-operator-mpl-cache'))

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
from PIL import Image

WIDTH, HEIGHT, DPI = 3200, 2304, 320
INK, MUTED, ACCENT, PAPER, RULE = '#182538', '#46576a', '#1c5485', '#ffffff', '#d5dfe8'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def baseline(config):
    path = HERE / 'baseline-before-visualization.json'
    if path.exists():
        return
    files = [*REPO.glob('README*.md')]
    for folder in ('skills', 'schemas', 'tests'):
        files.extend(p for p in (REPO / folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts)
    files.extend([REPO / 'docs/operators-v1.md', REPO / 'LICENSE'])
    record = dict(recorded_at_utc=datetime.now(timezone.utc).isoformat(),
        documentation_gate_at_baseline='INCOMPLETE: required README operator images absent',
        historical_technical_decisions='Preserved; this addendum adds a prospective mandatory documentation gate',
        sha256={p.relative_to(REPO).as_posix(): sha(p) for p in sorted(files)},
        operator_contract_version=config['version'])
    path.write_text(json.dumps(record, indent=2)+'\n', encoding='utf-8')


def draw(spec, config):
    plt.rcParams.update({'font.family': 'STIXGeneral', 'mathtext.fontset': 'stix',
                         'text.color': INK, 'savefig.facecolor': PAPER})
    fig = plt.figure(figsize=(WIDTH / DPI, HEIGHT / DPI), dpi=DPI, facecolor=PAPER)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_axis_off()
    ax.add_patch(Rectangle((.009, .012), .982, .976, linewidth=.7,
                          edgecolor=RULE, facecolor=PAPER, transform=ax.transAxes))
    texts = []
    def text(x, y, value, size=12.5, color=INK, ha='left', family=None, weight=None):
        artist = fig.text(x, y, value, fontsize=size, color=color, ha=ha, va='center',
                          family=family, fontweight=weight)
        texts.append(artist)
        return artist
    def label(x, y, value):
        return text(x, y, value, 10.2, ACCENT, family='DejaVu Sans', weight='bold')
    def rule(y):
        ax.plot([.06, .94], [y, y], color=RULE, linewidth=.7, transform=ax.transAxes)
    label(.06, .951, config['skill'].upper() + '  /  EVIDENCE OPERATORS  ' + config['version'])
    text(.06, .902, spec['name'], 28, weight='bold')
    text(.06, .859, spec['subtitle'], 12.5, MUTED)
    signature = text(.5, .791, '$' + spec['signature'] + '$', 25, ha='center')
    rule(.742)
    label(.06, .710, 'INPUT DOMAIN')
    label(.55, .710, 'OUTPUT DOMAIN')
    for i, value in enumerate(spec['inputs']):
        text(.06, .671 - i*.039, value, 12)
    for i, value in enumerate(spec['outputs']):
        text(.55, .671 - i*.039, value, 12)
    rule(.546)
    label(.06, .512, spec['relation_title'].upper())
    for i, value in enumerate(spec['relations']):
        text(.5, .459-i*spec.get('relation_step', .052), '$' + value + '$', spec.get('relation_size', 19), ha='center')
    label(.06, .336, spec['lower_title'].upper())
    for i, value in enumerate(spec['notes']):
        text(.06, .295-i*.035, value, 11.7, MUTED)
    rule(.144)
    text(.06, .107, spec['limit'], 11.6, INK)
    text(.06, .064, 'Bounded implementation contract · canonical source and tests · no formal proof claimed',
         9.8, MUTED, family='DejaVu Sans')
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    # Fit long formulae without clipping, retaining a readable minimum size.
    for artist in texts:
        limit = WIDTH * (.89 if artist.get_ha() == 'center' else .90)
        box = artist.get_window_extent(renderer)
        if box.width > limit:
            artist.set_fontsize(artist.get_fontsize() * limit / box.width)
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    bounds = []
    for artist in texts:
        box = artist.get_window_extent(renderer)
        assert box.x0 >= 32 and box.x1 <= WIDTH-32 and box.y0 >= 32 and box.y1 <= HEIGHT-32, (spec['name'], artist.get_text(), tuple(box.extents))
        bounds.append(dict(text=artist.get_text(), font_points=artist.get_fontsize(),
                           pixel_bounds=[round(v, 2) for v in box.extents]))
    # No two text lines may touch. Horizontal domain columns are disjoint.
    for i, left in enumerate(texts):
        for right in texts[i+1:]:
            a, b = left.get_window_extent(renderer), right.get_window_extent(renderer)
            assert not (min(a.x1,b.x1)>max(a.x0,b.x0) and min(a.y1,b.y1)>max(a.y0,b.y0)), (spec['name'], left.get_text(), right.get_text())
    target = HERE / spec['filename']
    fig.savefig(target, dpi=DPI, facecolor=PAPER, transparent=False,
                metadata={'Software': 'SeaFlow operator MathText renderer 1.0.0'})
    plt.close(fig)
    with Image.open(target) as image:
        image.load()
        assert image.size == (WIDTH, HEIGHT)
        assert image.getpixel((0, 0))[:3] == (255, 255, 255)
        if image.mode == 'RGBA':
            assert image.getchannel('A').getextrema() == (255,255)
    return dict(operator=spec['name'], path=target.relative_to(REPO).as_posix(),
        dimensions=[WIDTH,HEIGHT], dpi=DPI, sha256=sha(target), bytes=target.stat().st_size,
        source=spec['source_symbols'], readme_image_path=target.relative_to(REPO).as_posix(),
        contract=spec['contract'], text_bounds=bounds,
        mathematical_content=spec, no_clipping_or_text_overlap=True)


def main():
    config = json.loads((HERE/'formulas.json').read_text(encoding='utf-8'))
    baseline(config)
    implementation = REPO/config['implementation']
    tree = ast.parse(implementation.read_text(encoding='utf-8'))
    definitions = {n.name:n.lineno for n in ast.walk(tree) if isinstance(n,(ast.ClassDef,ast.FunctionDef))}
    records=[]
    for spec in config['operators']:
        for name in spec['source_symbols']:
            assert name in definitions, name
        record = draw(spec, config)
        record['implementation_lines']={name:definitions[name] for name in spec['source_symbols']}
        records.append(record)
    versions={name:importlib.metadata.version(name) for name in ('matplotlib','pillow','numpy','fonttools','kiwisolver','pyparsing','contourpy','cycler','packaging','python-dateutil','six')}
    report=dict(schema='seaflow-operator-visual-render/1.0.0', contract_version=config['version'],
        renderer='Matplotlib Agg / LaTeX-style MathText / STIX fonts',
        dependencies=versions, python=sys.version, style=dict(ink=INK,background=PAPER,accent=ACCENT),
        source_sha256={config['implementation']:sha(implementation), 'docs/operators-v1.md':sha(REPO/'docs/operators-v1.md'),
                       'docs/assets/operators/render.py':sha(Path(__file__)), 'docs/assets/operators/formulas.json':sha(HERE/'formulas.json')},
        visual_inspection='Recorded separately in visual-acceptance.json; rendering alone cannot pass the documentation gate',
        images=records)
    (HERE/'render-manifest.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n',encoding='utf-8')
    print(config['skill'] + ': ' + ', '.join(r['path'] for r in records))


if __name__ == '__main__':
    main()
