// 10분마다 깃허브 액션을 깨운다. 깨워도 할 일 없으면 액션이 바로 끝나니 중복은 안 난다.
async function wake(env, wf) {
  const r = await fetch(`https://api.github.com/repos/${env.GITHUB_REPO}/actions/workflows/${wf}/dispatches`, {
    method: "POST",
    headers: {
      authorization: `Bearer ${env.GITHUB_TOKEN.trim()}`,
      accept: "application/vnd.github+json",
      "content-type": "application/json",
      "user-agent": "shorts-wake",
    },
    body: JSON.stringify({ ref: "main" }),
  });
  const ok = r.status === 204;
  console.log(`${wf}: ${ok ? "깨움" : "실패 HTTP " + r.status + " " + (await r.text().catch(() => "")).slice(0, 120)}`);
  return ok;
}

async function wakeAll(env) {
  if (!env.GITHUB_TOKEN) { console.log("GITHUB_TOKEN 없음"); return {}; }
  const out = {};
  for (const wf of (env.WORKFLOWS || "").split(",").map((s) => s.trim()).filter(Boolean)) {
    out[wf] = await wake(env, wf).catch((e) => { console.log(`${wf}: ${e}`); return false; });
  }
  return out;
}

export default {
  async scheduled(_ctrl, env, ctx) { ctx.waitUntil(wakeAll(env)); },
  // 주소로 열면 상태만 보여 준다 (깨우진 않는다 — 아무나 눌러서 깃허브를 두드리지 못하게)
  async fetch(_req, env) {
    return new Response(JSON.stringify({ worker: "shorts-wake", repo: env.GITHUB_REPO, every: "10분", token: !!env.GITHUB_TOKEN }), {
      headers: { "content-type": "application/json; charset=utf-8" },
    });
  },
};
