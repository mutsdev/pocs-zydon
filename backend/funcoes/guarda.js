// Guarda de acesso comum as funcoes JS (embutida em cada uma por publicar_funcao.mjs).
// Regra: sessao obrigatoria, usuario ativo, e-mail do dominio configurado; executivo = e-mail do login.
async function comEspera(fazer) {
  for (let tentativa = 0; ; tentativa += 1) {
    try {
      return await fazer();
    } catch (erro) {
      if (!(erro && erro.status === 429) || tentativa >= 5) throw erro;
      await new Promise((ok) => setTimeout(ok, 1500 * (tentativa + 1)));
    }
  }
}
function paciente(mitra) {
  for (const k of ['executeQuery', 'executeDml']) {
    const original = mitra.sql[k].bind(mitra.sql);
    mitra.sql[k] = (...args) => comEspera(() => original(...args));
  }
  const fns = mitra.functions;
  if (fns) for (const k of ['executeAsync', 'execute']) {
    if (typeof fns[k] === 'function') { const o = fns[k].bind(fns); fns[k] = (...a) => comEspera(() => o(...a)); }
  }
  return mitra;
}
async function guarda(mitra, context) {
  paciente(mitra);
  const userId = context && context.userId;
  if (!userId) return { ok: false, erro: 'SEM_SESSAO', mensagem: 'Entre com a sua conta Google da Zydon.' };
  let r;
  try {
    r = await mitra.sql.executeQuery(`SELECT lower(u.email) AS email, u.enabled,
      (lower(u.email) LIKE '%@' || d.valor) AS dominio_ok, (lower(u.email) = a.valor) AS admin,
      e.id AS executivo_id, e.nome AS executivo, e.cargo
    FROM INT_USER u CROSS JOIN (SELECT valor FROM configuracao WHERE chave = 'dominio') d
    CROSS JOIN (SELECT valor FROM configuracao WHERE chave = 'admin_email') a
    LEFT JOIN executivos e ON lower(e.email) = lower(u.email) AND e.ativo
    WHERE u.user_id = CAST(:u AS UUID)`, { u: String(userId) });
  } catch (erro) {
    if (erro && erro.status === 429) {
      return { ok: false, erro: 'LIMITE_PLATAFORMA', mensagem: 'Muita gente usando ao mesmo tempo. Espere alguns segundos e tente de novo.' };
    }
    throw erro;
  }
  const s = (r.rows || [])[0];
  if (!s || !s.enabled || !s.dominio_ok) {
    return { ok: false, erro: 'ACESSO_RESTRITO', mensagem: 'Acesso restrito à equipe Zydon.' };
  }
  const sessao = { email: s.email, admin: !!s.admin, executivo_id: s.executivo_id, executivo: s.executivo, cargo: s.cargo };
  return { ok: true, sessao };
}
