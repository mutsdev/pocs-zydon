// Guarda de acesso comum as funcoes JS (embutida em cada uma por publicar_funcao.mjs).
// Regra: sessao obrigatoria, usuario ativo, e-mail do dominio configurado; executivo = e-mail do login.
async function guarda(mitra, context) {
  const userId = context && context.userId;
  if (!userId) return { ok: false, erro: 'SEM_SESSAO', mensagem: 'Entre com a sua conta Google da Zydon.' };
  const r = await mitra.sql.executeQuery(`SELECT lower(u.email) AS email, u.enabled,
      (lower(u.email) LIKE '%@' || d.valor) AS dominio_ok, (lower(u.email) = a.valor) AS admin,
      e.id AS executivo_id, e.nome AS executivo
    FROM INT_USER u CROSS JOIN (SELECT valor FROM configuracao WHERE chave = 'dominio') d
    CROSS JOIN (SELECT valor FROM configuracao WHERE chave = 'admin_email') a
    LEFT JOIN executivos e ON lower(e.email) = lower(u.email) AND e.ativo
    WHERE u.user_id = CAST(:u AS UUID)`, { u: String(userId) });
  const s = (r.rows || [])[0];
  if (!s || !s.enabled || !s.dominio_ok) {
    return { ok: false, erro: 'ACESSO_RESTRITO', mensagem: 'Acesso restrito à equipe Zydon.' };
  }
  const sessao = { email: s.email, admin: !!s.admin, executivo_id: s.executivo_id, executivo: s.executivo };
  return { ok: true, sessao };
}
