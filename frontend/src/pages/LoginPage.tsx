import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { MitraApiError } from '@mitralab.io/platform-sdk';
import { mitra, SIGN_IN_LINK_NOT_CLAIMED, takeSignInLinkOutcome } from '../lib/mitra-auth';
import { Card, CardContent } from '../components/ui/Card';
import Button from '../components/ui/Button';
import Input from '../components/ui/Input';

const loginErrorMessages: Record<string, string> = {
  APP_ACCESS_REQUIRED: 'Você ainda não tem acesso a este aplicativo.',
  APP_ACCESS_REVOKED: 'Seu acesso a este aplicativo foi removido.',
  SIGNUP_NOT_ALLOWED: 'Este aplicativo não aceita novos cadastros.',
  APP_ACCESS_LIMIT_REACHED: 'Este aplicativo atingiu o limite de usuários.',
  INVALID_CODE: 'Código incorreto.',
  // O IAM recusou ler o campo, que nesta tela é um endereço que não é um
  // endereço ou um código que não tem seis dígitos.
  VALIDATION_FAILED: 'Confira o que você digitou e tente de novo.',
  MAGIC_LINK_EXPIRED: 'Este pedido de entrada expirou. Peça um código novo.',
  MAGIC_LINK_USED: 'Este link de entrada já foi usado. Peça um código novo.',
  MAGIC_LINK_INVALID: 'Este link de entrada não é válido. Peça um código novo.',
  // Nada que a pessoa consiga contornar: a página em que ela está não é uma das
  // origens publicadas do aplicativo, e a frase neutra esconderia isso de quem
  // pode arrumar.
  INVALID_ORIGIN: 'A entrada por e-mail não está liberada para este endereço. O aplicativo precisa publicá-lo como uma das origens dele.',
};

// O boot achou um link que este navegador não conseguiu usar: o pedido de que
// ele precisa não está mais aqui. Ninguém recusou nada, então a frase não chama
// o link de usado nem de inválido, que são o MAGIC_LINK_USED e o
// MAGIC_LINK_INVALID acima, onde o IAM disse isso. Tomar emprestado a palavra
// deles mandaria a pessoa atrás de um problema que não existe: o link continua
// valendo para quem pediu. Aqui só se aponta o caminho que sempre funciona.
const SIGN_IN_LINK_NOT_CLAIMED_MESSAGE =
  'Este pedido de entrada não está mais disponível neste navegador. Informe seu e-mail para receber um código novo.';

// Popup que a pessoa fechou e pedido que estourou o tempo são como a SDK
// reporta quem desistiu da própria entrada, e nenhum dos dois é falha. Ela
// reporta os dois só pela mensagem, sem code para ler, então casar por texto é
// um acoplamento assumido: mudança de frase na SDK volta a pintar o banner.
const CANCELLED_SIGN_IN = /sign-in (was cancelled|timed out)\.$/;

const CODE_LENGTH = 6;
// Espelha o limite do IAM: o quinto erro invalida o desafio. Afrouxar só deste
// lado faria a tela contar tentativas que o servidor já recusa.
const MAX_CODE_ATTEMPTS = 5;

type SsoProvider = 'google' | 'microsoft';
type PendingAction = SsoProvider | 'email' | 'code';

// RATE_LIMITED é o único que precisa de número, e o número pode não vir: ele sai
// do Retry-After, que o navegador só enxerga quando o gateway expõe o header.
function describeLoginError(error: unknown): string {
  if (error instanceof MitraApiError && error.code === 'RATE_LIMITED') {
    return error.retryAfterSeconds
      ? `Muitas tentativas. Tente de novo em ${error.retryAfterSeconds} segundos.`
      : 'Muitas tentativas. Tente de novo daqui a pouco.';
  }

  const known =
    error instanceof MitraApiError && error.code ? loginErrorMessages[error.code] : undefined;
  if (known) return known;

  // Fora do dicionário a tela não repete o que veio: a mensagem que sobraria
  // nomeia internals e vem em inglês, e é assim que chegam as falhas de SSO, que
  // o boot também manda para cá. Este é o único ponto em que um texto de erro se
  // perde, então é daqui que ele vai para o console, em vez de espalhar log por
  // cada catch da tela.
  console.warn('Falha no login:', error);
  return 'Não foi possível entrar. Tente de novo.';
}

export default function LoginPage({ onLogin }: { onLogin: () => void }) {
  const navigate = useNavigate();
  const [pendingAction, setPendingAction] = useState<PendingAction | null>(null);
  const [error, setError] = useState('');

  // A entrada por e-mail tem dois passos, e o receipt os separa: sem ele a tela
  // pede o endereço, com ele pede o código que aquele endereço recebeu.
  const [email, setEmail] = useState('');
  const [receipt, setReceipt] = useState<string | null>(null);
  const [code, setCode] = useState('');
  const [attempts, setAttempts] = useState(0);
  const [resendIn, setResendIn] = useState(0);

  const isPending = pendingAction !== null;

  // O link da mensagem é concluído antes do primeiro render, então um link
  // vencido ou já gasto não tem onde se reportar além daqui. A sentinela não é
  // erro que o IAM respondeu e não carrega code, então é comparada por
  // identidade e tem frase própria.
  useEffect(() => {
    const outcome = takeSignInLinkOutcome();
    if (outcome === SIGN_IN_LINK_NOT_CLAIMED) {
      setError(SIGN_IN_LINK_NOT_CLAIMED_MESSAGE);
    } else if (outcome) {
      setError(describeLoginError(outcome));
    }
  }, []);

  // A contagem depende do booleano, não do número, para o intervalo nascer uma
  // vez por contagem em vez de ser refeito a cada segundo.
  const isCountingDown = resendIn > 0;
  useEffect(() => {
    if (!isCountingDown) return;
    const timer = setInterval(() => setResendIn((seconds) => Math.max(0, seconds - 1)), 1000);
    return () => clearInterval(timer);
  }, [isCountingDown]);

  async function handleSso(provider: SsoProvider) {
    setPendingAction(provider);
    setError('');

    try {
      if (provider === 'google') {
        await mitra.auth.signInWithGoogle({ mode: 'popup' });
      } else {
        await mitra.auth.signInWithMicrosoft({ mode: 'popup' });
      }
      onLogin();
      navigate('/', { replace: true });
    } catch (loginError) {
      // Desistência fica em silêncio, e só aqui: o boot também traz falha de
      // SSO, mas lá ninguém acabou de fechar popup nenhuma.
      const message = loginError instanceof Error ? loginError.message : '';
      if (!CANCELLED_SIGN_IN.test(message)) setError(describeLoginError(loginError));
    } finally {
      setPendingAction(null);
    }
  }

  // Passo um, e também o reenvio: pedir de novo substitui o pedido em voo, então
  // o receipt que vale é sempre o último.
  async function sendCode() {
    setPendingAction('email');
    setError('');

    try {
      const request = await mitra.auth.requestEmailCode({ email });
      setReceipt(request.receipt);
      setResendIn(request.resendAfterSeconds);
      setCode('');
      setAttempts(0);
    } catch (requestError) {
      // Pedido recusado traz a espera que ele quer, e ela alimenta a mesma
      // contagem que um pedido aceito alimenta. Os dois passos olham essa
      // contagem, porque os dois chegam aqui: o reenviar do passo do código e o
      // continuar do passo do endereço, que é onde cai a recusa do primeiro
      // pedido. Sem isto eles ficariam habilitados e a pessoa gastaria a espera
      // inteira levando recusa a cada clique.
      if (requestError instanceof MitraApiError && requestError.retryAfterSeconds) {
        setResendIn(requestError.retryAfterSeconds);
      }
      setError(describeLoginError(requestError));
    } finally {
      setPendingAction(null);
    }
  }

  // Volta ao passo do endereço. O pedido pendente acabou de um jeito ou de
  // outro, gasto ou abandonado, então nada dele sobrevive.
  function backToEmailStep(message: string) {
    setReceipt(null);
    setCode('');
    setAttempts(0);
    setResendIn(0);
    setError(message);
  }

  function reportVerificationFailure(verifyError: unknown) {
    const failureCode = verifyError instanceof MitraApiError ? verifyError.code : undefined;

    // Cobre o desafio criado pelo link, não o código digitado: para um código
    // contra desafio vencido o IAM responde INVALID_CODE.
    if (failureCode === 'MAGIC_LINK_EXPIRED' || failureCode === 'MAGIC_LINK_USED') {
      backToEmailStep(describeLoginError(verifyError));
      return;
    }
    if (failureCode !== 'INVALID_CODE') {
      setError(describeLoginError(verifyError));
      return;
    }

    const used = attempts + 1;
    setAttempts(used);
    if (used >= MAX_CODE_ATTEMPTS) {
      backToEmailStep('Muitas tentativas. Peça um código novo.');
      return;
    }
    setError(`${describeLoginError(verifyError)} Tentativa ${used} de ${MAX_CODE_ATTEMPTS}.`);
  }

  // Passo dois. A SDK transforma o código em sessão sozinha, não há nada para
  // adotar aqui.
  async function submitCode() {
    if (receipt === null) return;
    setPendingAction('code');
    setError('');

    try {
      await mitra.auth.verifyEmailCode({ receipt, code });
      onLogin();
      navigate('/', { replace: true });
    } catch (verifyError) {
      reportVerificationFailure(verifyError);
    } finally {
      setPendingAction(null);
    }
  }

  return (
    <div className="min-h-screen grid grid-cols-1 lg:grid-cols-2" style={{ backgroundColor: 'var(--color-bg)' }}>
      <div className="hidden lg:flex flex-col justify-between p-6" style={{ backgroundColor: 'var(--color-primary-bg)' }}>
        <div className="flex items-center gap-2">
          <svg width="32" height="32" viewBox="0 0 28 28" aria-hidden="true"><rect width="28" height="28" rx="7" fill="var(--color-primary)" /><path d="M8 9h12l-12 10h12" stroke="var(--color-on-primary)" strokeWidth="2.6" fill="none" strokeLinecap="round" strokeLinejoin="round" /></svg>
          <span className="text-base font-semibold" style={{ color: 'var(--color-text)' }}>POCs Zydon</span>
        </div>
        <div className="flex flex-col gap-3 max-w-md">
          <h2 className="text-2xl font-semibold" style={{ color: 'var(--color-text)' }}>Do site do cliente ao portal de demonstração</h2>
          <p className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>Informe o cliente e o site. Os produtos e os banners saem prontos para a sua curadoria, e você recebe o link do portal.</p>
        </div>
        <span className="text-meta" style={{ color: 'var(--color-text-secondary)' }}>Pré-vendas Zydon</span>
      </div>
      <div className="flex items-center justify-center p-4">
      <Card className="w-full max-w-sm animate-scaleIn">
        <CardContent className="pt-8 pb-6 px-6">
          {/* Header */}
          <div className="text-center mb-6">
            <h1 className="text-xl font-semibold" style={{ color: 'var(--color-text)' }}>
              POCs Zydon
            </h1>
            <p className="text-sm mt-1" style={{ color: 'var(--color-text-secondary)' }}>
              Portais de demonstração para os executivos comerciais
            </p>
          </div>

          {receipt ? (
            /* ── Email code ── */
            <form
              className="flex flex-col gap-3"
              onSubmit={(event) => {
                event.preventDefault();
                void submitCode();
              }}
            >
              <p className="text-sm text-center" style={{ color: 'var(--color-text-secondary)' }}>
                Enviamos um código de {CODE_LENGTH} dígitos para{' '}
                <span className="font-medium" style={{ color: 'var(--color-text)' }}>{email}</span>.
              </p>

              <Input
                label="Código"
                autoFocus
                inputMode="numeric"
                autoComplete="one-time-code"
                placeholder="000000"
                className="text-center tracking-[0.4em]"
                value={code}
                onChange={(event) => setCode(event.target.value.replace(/\D/g, '').slice(0, CODE_LENGTH))}
                disabled={isPending}
              />

              <Button type="submit" size="lg" className="w-full" disabled={isPending || code.length < CODE_LENGTH}>
                {pendingAction === 'code' ? 'Aguarde...' : 'Entrar'}
              </Button>

              <div className="flex items-center justify-between text-sm">
                <button
                  type="button"
                  className="cursor-pointer hover:underline disabled:cursor-not-allowed disabled:no-underline disabled:opacity-50"
                  style={{ color: 'var(--color-text-secondary)' }}
                  onClick={() => backToEmailStep('')}
                  disabled={isPending}
                >
                  Usar outro e-mail
                </button>
                <button
                  type="button"
                  className="cursor-pointer hover:underline disabled:cursor-not-allowed disabled:no-underline disabled:opacity-50"
                  style={{ color: 'var(--color-text-secondary)' }}
                  onClick={() => void sendCode()}
                  disabled={isPending || isCountingDown}
                >
                  {isCountingDown ? `Reenviar em ${resendIn}s` : 'Reenviar código'}
                </button>
              </div>
            </form>
          ) : (
            <>
              {/* ── SSO ── */}
              <div className="flex flex-col gap-3">
                <Button variant="secondary" size="lg" className="w-full" onClick={() => handleSso('google')} disabled={isPending}>
                  <svg width="18" height="18" viewBox="0 0 24 24" aria-hidden="true">
                    <path d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92a5.06 5.06 0 0 1-2.2 3.32v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.1z" fill="#4285F4" />
                    <path d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" fill="#34A853" />
                    <path d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z" fill="#FBBC05" />
                    <path d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" fill="#EA4335" />
                  </svg>
                  {pendingAction === 'google' ? 'Aguarde...' : 'Continue com Google'}
                </Button>

                <Button variant="secondary" size="lg" className="w-full" onClick={() => handleSso('microsoft')} disabled={isPending}>
                  <svg width="18" height="18" viewBox="0 0 24 24" aria-hidden="true">
                    <rect x="1" y="1" width="10" height="10" fill="#F25022" />
                    <rect x="13" y="1" width="10" height="10" fill="#7FBA00" />
                    <rect x="1" y="13" width="10" height="10" fill="#00A4EF" />
                    <rect x="13" y="13" width="10" height="10" fill="#FFB900" />
                  </svg>
                  {pendingAction === 'microsoft' ? 'Aguarde...' : 'Continue com Microsoft'}
                </Button>
              </div>

              {/* ── Email ──
                  O IAM só serve a entrada por e-mail aos aplicativos liberados e
                  responde um 202 neutro aos demais. Um aplicativo fora dessa
                  lista ofereceria um formulário que deixa a pessoa esperando um
                  código que ninguém vai mandar. Google e Microsoft não têm lista
                  e aparecem sempre. */}
              {mitra.emailLoginEnabled && (
                <>
                  <div className="flex items-center gap-3 my-4">
                    <span className="h-px flex-1" style={{ backgroundColor: 'var(--color-border)' }} />
                    <span className="text-meta" style={{ color: 'var(--color-text-secondary)' }}>ou</span>
                    <span className="h-px flex-1" style={{ backgroundColor: 'var(--color-border)' }} />
                  </div>

                  <form
                    className="flex flex-col gap-3"
                    onSubmit={(event) => {
                      event.preventDefault();
                      void sendCode();
                    }}
                  >
                    <Input
                      label="E-mail"
                      type="email"
                      autoComplete="email"
                      placeholder="voce@exemplo.com"
                      value={email}
                      onChange={(event) => {
                        setEmail(event.target.value);
                        // Qualquer edição do campo solta o botão, inclusive
                        // voltar ao mesmo endereço. Quem enforça a espera é o
                        // IAM, que re-arma a contagem pelo retryAfterSeconds na
                        // próxima recusa.
                        setResendIn(0);
                      }}
                      disabled={isPending}
                      required
                    />

                    <Button
                      type="submit"
                      size="lg"
                      className="w-full"
                      disabled={isPending || isCountingDown || !email.trim()}
                    >
                      {pendingAction === 'email'
                        ? 'Aguarde...'
                        : isCountingDown
                          ? `Tente de novo em ${resendIn}s`
                          : 'Continuar com e-mail'}
                    </Button>
                  </form>
                </>
              )}
            </>
          )}

          {/* Error */}
          {error && (
            <p className="text-sm text-center mt-4 animate-fadeIn" style={{ color: 'var(--color-danger)' }}>{error}</p>
          )}
        </CardContent>
      </Card>
      </div>
    </div>
  );
}
