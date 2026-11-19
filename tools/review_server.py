"""审校界面 v2：问题清单 + 跳转 + 差异对比 + 术语表。

启动：python tools/review_server.py [port]
打开：http://127.0.0.1:8765
"""

from __future__ import annotations

import difflib
import json
import re
import subprocess
import sys
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from epubtr.epub import open_book, read_doc      # noqa: E402
from epubtr.glossary import check as gl_check, load as gl_load  # noqa: E402
from epubtr.ir import extract_doc                 # noqa: E402
from epubtr.names import NameResolver             # noqa: E402
from epubtr.package import plain                  # noqa: E402
from epubtr.paths import slug as make_slug         # noqa: E402
from epubtr.store import save_json                 # noqa: E402
from epubtr.punct import check_text
from epubtr.textnorm import looks_japanese               # noqa: E402

KANA = re.compile(r"[\u3040-\u30ff]")
CACHE: dict[str, dict] = {}


def slug(s: str) -> str:
    return make_slug(s)


def books() -> list[dict]:
    out = []
    for epub in sorted((ROOT / "assets" / "samples").glob("*.epub")):
        book, _ = open_book(epub)
        s = slug(book.title or epub.stem)
        work = ROOT / "work" / s
        if not work.exists():
            continue
        out.append({"slug": s, "title": book.title, "epub": str(epub),
                    "has_rev": (work / "rev").exists()})
    return out


def load_book(s: str) -> dict:
    if s in CACHE:
        return CACHE[s]
    info = next(b for b in books() if b["slug"] == s)
    book, z = open_book(Path(info["epub"]))
    kb = ROOT / "kb" / s
    bible = json.loads((kb / "auto_bible.json").read_text(encoding="utf-8")) \
        if (kb / "auto_bible.json").exists() else {}
    glossary = gl_load(kb)
    work = ROOT / "work" / s
    draft, rev = {}, {}
    for f in sorted(work.glob("*.json")):
        if f.name == "titles.json":
            continue
        data = json.loads(f.read_text(encoding="utf-8"))
        draft[data["href"]] = data["units"]
        rp = work / "rev" / f.name
        rev[data["href"]] = json.loads(rp.read_text(encoding="utf-8"))["units"] \
            if rp.exists() else data["units"]
    CACHE[s] = {"book": book, "z": z, "kb": kb, "bible": bible,
                "gl": glossary, "draft": draft, "rev": rev,
                "names": NameResolver(glossary), "info": info,
                "docs": {it.full: it for it in book.docs}}
    return CACHE[s]


def doc_blocks(b: dict, href: str):
    return extract_doc(href, read_doc(b["z"], b["docs"][href])).blocks


def issues(s: str) -> list[dict]:
    b = load_book(s)
    out: list[dict] = []
    for href, units in b["rev"].items():
        blocks = doc_blocks(b, href)
        # 标点：整篇连检，映射到段落
        text = "\n".join(units.values())
        spans, pos = [], 0
        for uid, val in units.items():
            spans.append((pos, pos + len(val), uid))
            pos += len(val) + 1

        def uid_at(off: int) -> str:
            for a, e, uid in spans:
                if a <= off <= e:
                    return uid
            return "?"

        for off, msg in check_text(text)[:20]:
            if msg.startswith("未闭合"):
                # 日文对话跨段时，中间段落本来就不闭合，不作为待办
                continue
            out.append({"type": "标点", "doc": href, "uid": uid_at(off),
                        "note": f"{msg}（检查引号/括号是否成对）"})
        # 术语 / 假名
        for blk in blocks:
            zh = units.get(blk.uid, "")
            bad = gl_check(b["gl"], blk.source, zh)
            if bad:
                ja, _, zz = bad[0].partition("→")
                if ja == zz:
                    note = (f"原文出现了「{ja}」，但译文里没有完整出现"
                            f"（可能被简写或漏译）")
                else:
                    note = f"原文有「{ja}」，译文应出现「{zz}」，但没找到"
                out.append({"type": "术语", "doc": href, "uid": blk.uid,
                            "note": note})
            if looks_japanese(zh):
                out.append({"type": "未译", "doc": href, "uid": blk.uid,
                            "note": "这段看起来仍是日文，可能翻译失败后回退成了原文"})
            hits = KANA.findall(zh)
            if len(hits) > 3:
                sample = "".join(sorted(set(hits)))[:12]
                out.append({"type": "假名", "doc": href, "uid": blk.uid,
                            "note": f"译文里有 {len(hits)} 个假名（{sample}…），"
                                    f"可能有未译内容"})
    # 原文变更
    stale = ROOT / "reports" / s / "stale.json"
    if stale.exists():
        for item in json.loads(stale.read_text(encoding="utf-8"))[:50]:
            href, uid = item.rsplit(":", 1)
            out.append({"type": "待重译", "doc": href, "uid": uid,
                        "note": "原文在 IR 变更后已不同，旧译文不可用"})
    return out[:200]


def unit_detail(s: str, href: str, uid: str) -> dict:
    b = load_book(s)
    blk = next((x for x in doc_blocks(b, href) if x.uid == uid), None)
    if blk is None:
        return {"error": "not found"}
    draft = b["draft"].get(href, {}).get(uid, "")
    rev = b["rev"].get(href, {}).get(uid, "")
    if draft == rev:
        diff = '<span class="same">初稿与修订相同（这里的问题属于术语/标点，不是改写）</span>'
    else:
        sm = difflib.SequenceMatcher(None, draft, rev)
        html = []
        for op, i1, i2, j1, j2 in sm.get_opcodes():
            if op == "equal":
                html.append(_esc(rev[j1:j2]))
            elif op == "delete":
                html.append(f"<del>{_esc(draft[i1:i2])}</del>")
            elif op == "insert":
                html.append(f"<ins>{_esc(rev[j1:j2])}</ins>")
            else:
                html.append(f"<del>{_esc(draft[i1:i2])}</del>"
                            f"<ins>{_esc(rev[j1:j2])}</ins>")
        diff = "".join(html)
    return {"doc": href, "uid": uid, "ja": plain(blk.source),
            "draft": draft, "rev": rev, "diff": diff}


def _esc(t: str) -> str:
    return t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


PAGE = r"""<!doctype html><html lang="zh"><meta charset="utf-8"><title>审校台</title>
<style>
 *{box-sizing:border-box}
 body{font:15px/1.7 -apple-system,"Segoe UI",sans-serif;margin:0;display:flex;height:100vh;color:#222}
 #side{width:340px;border-right:1px solid #e5e5e5;background:#fafafa;display:flex;flex-direction:column}
 #side h3{font-size:13px;color:#888;margin:14px 12px 4px}
 #list{overflow:auto;flex:1}
 #main{flex:1;overflow:auto;padding:22px 30px}
 .item{padding:7px 12px;cursor:pointer;border-left:3px solid transparent;font-size:14px}
 .item:hover{background:#f0f0f0}
 .item.sel{background:#e8f0fe;border-left-color:#3b82f6}
 .row{margin:12px 0}
 .muted{color:#888;font-size:13px}
 input,textarea{width:100%;font:inherit;padding:7px;border:1px solid #ddd;border-radius:6px}
 textarea{min-height:120px}
 button{padding:7px 14px;margin-right:8px;border:1px solid #ddd;background:#fff;border-radius:6px;cursor:pointer}
 button.primary{background:#2563eb;color:#fff;border-color:#2563eb}
 .ja{background:#f6f6f6;padding:10px;border-radius:6px;white-space:pre-wrap}
 del{background:#fee2e2;text-decoration:line-through;color:#991b1b}
 ins{background:#dcfce7;text-decoration:none;color:#166534}
 .same{color:#888;font-style:italic}
 .issue{background:#fff7ed;border:1px solid #fed7aa;color:#9a3412;
        padding:10px 12px;border-radius:6px;margin:10px 0;font-size:14px}
 .badge{background:#fee2e2;color:#b91c1c;border-radius:4px;padding:1px 6px;font-size:12px;margin-right:6px}
 .gl{display:flex;gap:6px;padding:4px 12px;align-items:center}
 .gl input{flex:1;padding:4px 6px}
 .gl b{min-width:100px;font-size:13px}
</style>
<div id="side">
 <h3>书籍</h3><div id="books"></div>
 <h3>问题清单</h3><div id="issues"></div>
 <h3>待确认绰号</h3><div id="aliases"></div>
 <h3>术语表 <input id="q" placeholder="搜索…" style="width:140px;padding:2px 6px;font-size:12px"></h3>
 <div id="gls"></div>
</div>
<div id="main"><p class="muted">选一本书开始。</p></div>
<div style="position:fixed;right:22px;bottom:18px">
 <button class="primary" onclick="build()">重新打包</button><span id="msg" class="muted"></span>
</div>
<script>
let book=null;
function seenKey(doc,uid){return book+'|'+doc+'|'+uid}
function seenSet(){return new Set(JSON.parse(localStorage.getItem('seen')||'[]'))}
function markSeen(doc,uid){const s=seenSet();s.add(seenKey(doc,uid));
 localStorage.setItem('seen',JSON.stringify([...s]));loadIssues();$('main').innerHTML='<p class="muted">已标记，剩余问题见左侧。</p>';}
async function api(p,o){const r=await fetch(p,o);return r.json()}
const $=id=>document.getElementById(id);
$('q').oninput=()=>loadGlossary($('q').value);
async function init(){
 const bs=await api('/api/books');
 bs.forEach(b=>{const d=document.createElement('div');d.className='item';
  d.textContent=b.title;d.onclick=()=>sel(b.slug);$('books').appendChild(d)});
}
async function sel(s){book=s;$('main').innerHTML='<p class="muted">加载中…</p>';
 await Promise.all([loadIssues(),loadAliases(),loadGlossary('')]);
 $('main').innerHTML='<h2>'+s+'</h2><p class="muted">从左侧问题清单开始。</p>';}
async function loadIssues(){
 const xs=await api(`/api/book/${encodeURIComponent(book)}/issues`);$('issues').innerHTML='';
 const seen=seenSet();
 const rest=xs.filter(x=>!seen.has(seenKey(x.doc,x.uid)));
 if(!rest.length)$('issues').innerHTML='<div class="muted" style="padding:0 12px">无</div>';
 rest.forEach(x=>{const d=document.createElement('div');d.className='item';
  d.innerHTML=`<span class="badge">${x.type}</span>${x.uid}`;
  d.title=x.note;
  d.onclick=()=>openUnit(x);$('issues').appendChild(d)});
}
async function loadAliases(){
 const xs=await api(`/api/book/${encodeURIComponent(book)}/aliases`);$('aliases').innerHTML='';
 if(!xs.length)$('aliases').innerHTML='<div class="muted" style="padding:0 12px">无</div>';
 xs.forEach(x=>{const d=document.createElement('div');d.className='item';
  d.innerHTML=`<b>${x.ja}</b> <span class="muted">→ ${x.owner_zh||x.owner}</span>`;
  d.onclick=()=>{$('main').innerHTML=`<h2>确认绰号</h2><p class="muted">${x.ja} → ${x.owner_zh||x.owner}</p>
   <input id="f" placeholder="中文绰号"><p><button class="primary" onclick="saveGl('${x.ja}',$('f').value)">写入术语表</button></p>`};$('aliases').appendChild(d)});
}
async function loadGlossary(q){
 const xs=await api(`/api/book/${encodeURIComponent(book)}/glossary`);$('gls').innerHTML='';
 xs.filter(x=>!q||x.ja.includes(q)||x.zh.includes(q)).slice(0,200).forEach(x=>{
  const d=document.createElement('div');d.className='gl';
  d.innerHTML=`<b>${x.ja}</b><input value="${(x.zh||'').replace(/"/g,'&quot;')}">`;
  const btn=document.createElement('button');btn.textContent='存';
  btn.onclick=()=>saveGl(x.ja,d.querySelector('input').value);d.appendChild(btn);$('gls').appendChild(d)});
}
async function openUnit(x){
 const doc=x.doc, uid=x.uid;
 const d=await api(`/api/book/${encodeURIComponent(book)}/unit?doc=${encodeURIComponent(doc)}&uid=${uid}`);
 $('main').innerHTML=`<h2>${uid}</h2><div class="muted">${doc}</div>
 <div class="issue"><b>${x.type}：</b>${x.note||''}</div>
 <div class="row"><div class="muted">日文</div><div class="ja">${d.ja.replace(/</g,'&lt;')}</div></div>
 <div class="row"><div class="muted">修订差异（红=删，绿=改）</div><div class="ja">${d.diff}</div></div>
 <div class="row"><div class="muted">译文（可改）</div><textarea id="f">${d.rev.replace(/</g,'&lt;')}</textarea></div>
 <button class="primary" onclick="saveUnit('${doc}','${uid}')">保存</button>
 <button onclick="revert('${doc}','${uid}')">用初稿</button>
 <button onclick="markSeen('${doc}','${uid}')">标记已看</button>`;
}
async function saveGl(ja,zh){if(!zh)return;
 await api(`/api/book/${encodeURIComponent(book)}/glossary`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({ja,zh})});
 $('msg').textContent='术语已存';loadAliases();loadGlossary($('q').value);}
async function saveUnit(doc,uid){
 await api(`/api/book/${encodeURIComponent(book)}/unit`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({doc,uid,text:$('f').value})});
 $('msg').textContent='译文已存';loadIssues();}
async function revert(doc,uid){
 const d=await api(`/api/book/${encodeURIComponent(book)}/unit?doc=${encodeURIComponent(doc)}&uid=${uid}`);
 $('f').value=d.draft;await saveUnit(doc,uid);}
async function build(){$('msg').textContent='打包中…';
 const r=await api(`/api/book/${encodeURIComponent(book)}/build`,{method:'POST'});
 $('msg').textContent=r.ok?'已生成':'失败';}
init();
</script></html>"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"),
                   "application/json")

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(u.query)
        if u.path == "/":
            return self._send(200, PAGE.encode("utf-8"), "text/html; charset=utf-8")
        if u.path == "/api/books":
            return self._json(books())
        m = re.match(r"^/api/book/([^/]+)/(issues|aliases|glossary|unit)$", u.path)
        if m:
            s = urllib.parse.unquote(m.group(1))
            b = load_book(s)
            if m.group(2) == "issues":
                return self._json(issues(s))
            if m.group(2) == "aliases":
                have = {c["ja"] for c in b["gl"]["characters"]}
                zh_of = {c["ja"]: c["zh"] for c in b["gl"]["characters"]}
                out = []
                for c in b["bible"].get("characters", []):
                    for a in c.get("aliases", []):
                        if len(a) >= 2 and a not in have and a != c.get("name_ja"):
                            out.append({"ja": a, "owner": c.get("name_ja", ""),
                                        "owner_zh": zh_of.get(c.get("name_ja", ""), "")})
                return self._json(out)
            if m.group(2) == "glossary":
                return self._json(b["gl"].get("characters", []) + b["gl"].get("terms", []))
            href = q.get("doc", [""])[0]
            uid = q.get("uid", [""])[0]
            return self._json(unit_detail(s, href, uid))
        self._send(404, b"not found", "text/plain")

    def do_POST(self):
        u = urllib.parse.urlparse(self.path)
        m = re.match(r"^/api/book/([^/]+)/(glossary|unit|build)$", u.path)
        if not m:
            return self._send(404, b"not found", "text/plain")
        s = urllib.parse.unquote(m.group(1))
        b = load_book(s)
        n = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(n) or b"{}")
        action = m.group(2)
        if action == "glossary":
            ja, zh = body.get("ja", ""), body.get("zh", "")
            for c in b["gl"]["characters"]:
                if c["ja"] == ja:
                    c["zh"] = zh
                    break
            else:
                b["gl"]["characters"].append({"ja": ja, "zh": zh, "note": "confirmed"})
            save_json(b["kb"] / "glossary.json", b["gl"])
            CACHE.pop(s, None)
            return self._json({"ok": True})
        if action == "unit":
            href, uid, text = body.get("doc"), body.get("uid"), body.get("text", "")
            idx = next((i for i, it in enumerate(b["book"].docs) if it.full == href), 0)
            f = ROOT / "work" / s / "rev" / f"{idx:03d}.json"
            data = json.loads(f.read_text(encoding="utf-8"))
            data["units"][uid] = text
            save_json(f, data)
            b["rev"][href][uid] = text
            # 如果这一段是书名/章节标题，同步标题表，否则打包时会被覆盖
            blk = next((x for x in doc_blocks(b, href) if x.uid == uid), None)
            tp = ROOT / "work" / s / "titles.json"
            if blk is not None and tp.exists():
                titles = json.loads(tp.read_text(encoding="utf-8"))
                key = plain(blk.source)
                if key in titles and titles[key] != text:
                    titles[key] = text
                    save_json(tp, titles)
            return self._json({"ok": True})
        try:
            r = subprocess.run([sys.executable, "tools/build_epub.py", b["info"]["epub"]],
                               cwd=ROOT, capture_output=True, text=True, timeout=600)
            out = "out/" + (Path(b["info"]["epub"]).stem.split(" (")[0] + ".zh.epub")
            return self._json({"ok": r.returncode == 0, "out": out,
                               "error": (r.stderr or r.stdout)[-300:]})
        except Exception as e:  # noqa: BLE001
            return self._json({"ok": False, "error": str(e)})


def main() -> int:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"http://127.0.0.1:{port}")
    srv.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
