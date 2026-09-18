"""Bundled helper resources, carried by the Python package without build changes."""

PAGE = '''<!doctype html>
<html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>치pdf · 번역 도우미</title>
<style>
body{font:16px/1.65 system-ui,sans-serif;background:#f2f5f8;color:#253345;margin:0;padding:28px}
main{max-width:540px;margin:24px auto;background:white;padding:28px;border-radius:16px}
h1{font-size:23px;margin:0 0 10px}p{margin:10px 0}button{background:#286b60;color:white;border:0;border-radius:8px;padding:12px 20px;font:inherit;cursor:pointer}
button:disabled{opacity:.55;cursor:wait}#status{white-space:pre-wrap;background:#edf4f1;padding:14px;border-radius:8px}small{color:#5b6978}
</style>
<main><h1>치pdf 번역 도우미</h1><p>일본어를 한국어로 번역합니다. 준비를 마치면 치pdf에서 번역할 문장을 선택하세요.</p>
<button id="prepare">번역 준비</button><p id="status" role="status" aria-live="polite">연결 중…</p>
<p><small>첫 사용 시 Chrome가 언어팩을 내려받습니다. 번역은 이 PC에서 처리되며 API 키나 구독은 필요하지 않습니다.</small></p>
<p><small>번역하는 동안 이 창을 열어 두세요. 창을 닫았다면 치pdf의 ‘Chrome 연결’로 다시 열 수 있습니다.</small></p></main>
<script src="/bridge.js" defer></script></html>'''

SCRIPT = r'''
"use strict";
const token = location.hash.slice(1) || sessionStorage.getItem("chipdfToken") || "";
if (token) sessionStorage.setItem("chipdfToken", token);
history.replaceState(null, "", "/");
const client = crypto.randomUUID();
const status = document.getElementById("status");
const prepare = document.getElementById("prepare");
let translator = null, state = "waiting", message = "번역 준비를 눌러 주세요.";
let busy = false, stopped = false, job = null, aborter = null, preparing = false;
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
function show(next, text) {
  state = next; message = text; status.textContent = text;
  prepare.disabled = preparing || busy || stopped || next === "unsupported";
}
async function api(path, extra = {}) {
  const response = await fetch(path, {method:"POST", cache:"no-store",
    headers:{"Content-Type":"application/json", "Authorization":"Bearer " + token},
    body:JSON.stringify({client, state, message, ...extra}), signal:AbortSignal.timeout(8000)});
  const body = await response.json();
  if (!response.ok || body.error) {
    stopped = true;
    throw new Error(body.error || "치pdf 연결이 종료되었습니다.");
  }
  return body;
}
function resetTranslator() {
  if (aborter) aborter.abort();
  if (translator) { try { translator.destroy(); } catch (_) {} }
  translator = null;
}
prepare.addEventListener("click", async () => {
  if (busy || preparing || stopped) return;
  preparing = true;
  show("downloading", "번역기를 준비합니다. 첫 사용 시 언어팩을 내려받습니다…");
  resetTranslator();
  try {
    // Invoke create directly from the user's browser click, before any await.
    const creating = Translator.create({sourceLanguage:"ja", targetLanguage:"ko", monitor(monitor) {
      monitor.addEventListener("downloadprogress", event => {
        show("downloading", `언어팩 준비 ${Math.round(Math.min(1, Math.max(0, event.loaded)) * 100)}%`);
      });
    }});
    translator = await creating;
    if (stopped) { resetTranslator(); return; }
    show("ready", "준비되었습니다. 치pdf에서 번역을 시작하세요.");
  } catch (_) {
    show("error", "번역기를 준비하지 못했습니다. 인터넷 연결과 Chrome 업데이트를 확인한 뒤 번역 준비를 다시 눌러 주세요.");
  } finally {
    preparing = false;
    prepare.disabled = stopped || busy;
  }
});
async function translate(next) {
  busy = true; job = next; aborter = new AbortController();
  show("busy", "문단을 번역하고 있습니다…");
  try {
    const target = await translator.translate(next.text, {signal:aborter.signal});
    if (!aborter.signal.aborted && !stopped) {
      await api("/api/result", {id:next.id, source_hash:next.source_hash, target:String(target)});
    }
  } catch (error) {
    if (!stopped && !aborter.signal.aborted) {
      try { await api("/api/result", {id:next.id, source_hash:next.source_hash,
        error:"Chrome 번역에 실패했습니다. 번역 준비를 다시 누르거나 원문을 짧은 문단으로 나눠 주세요."}); } catch (_) {}
      resetTranslator();
    }
  } finally {
    busy = false; job = null; aborter = null;
    if (!stopped) show(translator ? "ready" : "waiting",
      translator ? "준비되었습니다. 치pdf에서 계속 작업하세요." : "번역이 중단되었습니다. 계속하려면 번역 준비를 눌러 주세요.");
  }
}
async function heartbeat() {
  while (!stopped) {
    try {
      const result = await api("/api/heartbeat", {job:job?.id || ""});
      if (result.cancel && job) resetTranslator();
    } catch (_) {
      stopped = true; resetTranslator();
      show("error", "치pdf와의 연결이 종료되었습니다. 앱의 Chrome 연결 버튼으로 다시 열어 주세요.");
    }
    await delay(2000);
  }
}
async function poll() {
  while (!stopped) {
    try {
      if (!busy) {
        const result = await api("/api/poll");
        if (result.job && translator && state === "ready") await translate(result.job);
      }
    } catch (_) {
      stopped = true; resetTranslator();
      show("error", "번역 연결이 종료되었습니다. 치pdf의 Chrome 연결로 다시 열어 주세요.");
    }
    await delay(600);
  }
}
async function start() {
  if (!token) { stopped = true; show("error", "치pdf의 Chrome 연결 버튼으로 열어 주세요."); return; }
  prepare.disabled = true;
  if (!isSecureContext || !("Translator" in self)) {
    show("unsupported", "이 Chrome에서는 내장 번역을 사용할 수 없습니다. Chrome를 업데이트하거나 앱에서 오프라인 번역을 선택하세요.");
  } else {
    try {
      const available = await Translator.availability({sourceLanguage:"ja", targetLanguage:"ko"});
      if (available === "unavailable") show("unsupported", "이 기기에서 일본어 → 한국어 번역을 사용할 수 없습니다.");
      else show("waiting", "번역 준비를 눌러 주세요. 필요한 언어팩은 Chrome가 준비합니다.");
    } catch (_) { show("waiting", "번역 준비를 눌러 연결을 시작하세요."); }
  }
  heartbeat(); poll();
}
start();
'''
