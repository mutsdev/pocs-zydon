import { createClient } from '@mitralab.io/platform-sdk';

export const mitra = createClient({
  appId: import.meta.env.VITE_MITRA_APP_ID,
  apiUrl: import.meta.env.VITE_MITRA_API_URL,
});

interface PreviewSession {
  baseURL: string;
  token: string;
  refreshToken?: string;
}

// O preview tem dois gatilhos. O fragmento vale sempre que estiver presente: o
// builder compõe o endereço do iframe e, no modo embedded, nem nomeia o iframe.
// O handshake por postMessage só roda quando o iframe se chama 'mitra-preview',
// e o nome só decide se ele é tentado. No postMessage a confiança vem da
// validação de origin e source; no fragmento, do escopo do token (ver abaixo).
const PREVIEW_IFRAME_NAME = 'mitra-preview';
const PREVIEW_TOKEN_PARAM = 'previewToken';
const PREVIEW_REFRESH_TOKEN_PARAM = 'previewRefreshToken';
const PREVIEW_LOGIN_REQUEST_TYPE = 'mitra-preview-login-request';
const PREVIEW_LOGIN_RESPONSE_TYPE = 'mitra-preview-login-response';
const PREVIEW_LOGIN_TIMEOUT_MS = 5000;
const APP_ID = import.meta.env.VITE_MITRA_APP_ID;
const AUTH_URL = import.meta.env.VITE_MITRA_AUTH_URL;

// Parâmetro do fragmento em que o link da mensagem de entrada chega, o mesmo que
// a SDK lê.
const SIGN_IN_LINK_PARAM = 'emailToken';

// O que o boot deixa quando a URL trouxe um link de entrada que este navegador
// não conseguiu usar. Não é um MitraApiError e não finge ser: nesse caminho
// nenhum servidor recusou nada, então não existe 'code' para ler e inventar um
// colocaria palavra na boca do IAM. A tela de login separa os dois por
// identidade e escreve a própria frase.
export const SIGN_IN_LINK_NOT_CLAIMED = Symbol('signInLinkNotClaimed');

// A conclusão roda antes do primeiro render, então o que ela tem a dizer não tem
// tela onde se reportar. Fica aqui esperando a tela de login, que consome numa
// leitura só.
//
// Quem não deixa isto envelhecer é o initMitra: quando o boot termina
// autenticado a tela de login não chega a montar, e então o slot morre junto com
// o boot. Sem essa soltura ele ficaria guardado pelo resto da vida do documento,
// porque neste template nada recarrega a página: o clearSession chama signOut()
// sem URL e o App.tsx apenas troca de rota. O primeiro /login depois de um
// logout leria a frase do boot de minutos atrás, e quem acabou de clicar em sair
// receberia um aviso sobre um link de entrada que não tem relação com o que ele
// fez.
let signInLinkOutcome: unknown = null;

// Consome numa leitura só o que o boot deixou em signInLinkOutcome.
export function takeSignInLinkOutcome(): unknown {
  const outcome = signInLinkOutcome;
  signInLinkOutcome = null;
  return outcome;
}

// Só a presença do link é lida, e é lida antes da SDK rodar porque a SDK tira o
// token da URL. O valor nunca é guardado, logado nem repassado: a SDK continua
// sendo a única coisa que faz algo com ele.
function carriesSignInLink(): boolean {
  const hash = window.location.hash.replace(/^#/, '');
  return (new URLSearchParams(hash).get(SIGN_IN_LINK_PARAM) ?? '').trim() !== '';
}

type PreviewFragmentSession = Pick<PreviewSession, 'token' | 'refreshToken'>;

// Tira do fragmento apenas os dois parâmetros, preservando o resto do texto
// original: reescrever o hash inteiro quebraria rota em hash, como '#/home'.
function removePreviewFragmentParams(hash: string): void {
  const rest = hash
    .split('&')
    .filter((part) => {
      // A chave é decodificada do mesmo jeito que a leitura decodifica, senão
      // uma chave escrita como '%70reviewToken' seria lida e não seria removida.
      const [key] = new URLSearchParams(part).keys();
      return key !== PREVIEW_TOKEN_PARAM && key !== PREVIEW_REFRESH_TOKEN_PARAM;
    })
    .join('&');

  try {
    window.history.replaceState(
      {},
      '',
      window.location.pathname + window.location.search + (rest ? `#${rest}` : ''),
    );
  } catch {
    // Iframe em sandbox pode recusar replaceState. O token já foi lido, e manter
    // a sessão vale mais do que descartá-la por causa da limpeza da URL.
  }
}

// Lê a sessão que o builder escreveu no fragmento do endereço do iframe. Não há
// origin para conferir aqui, e o que sobra prova menos do que parece: o token é
// escopado neste app e a SDK recusa token de outro app, mas o app publicado não
// manda frame-ancestors, então qualquer site pode enquadrá-lo e entregar uma
// sessão de uma conta dele. Esse risco foi aceito conscientemente na decisão
// que trocou o handshake pelo fragmento, em mitralab-dev/mitra-web#938.
function readPreviewSessionFromFragment(): PreviewFragmentSession | null {
  try {
    const hash = window.location.hash.slice(1);
    if (!hash) return null;

    const hashParams = new URLSearchParams(hash);
    if (
      !hashParams.has(PREVIEW_TOKEN_PARAM) &&
      !hashParams.has(PREVIEW_REFRESH_TOKEN_PARAM)
    ) {
      return null;
    }

    // Limpa antes de decidir se a sessão serve: o refresh token é a credencial
    // mais longeva e não pode ficar na barra nem no histórico, mesmo quando o
    // access token não veio junto ou veio vazio.
    removePreviewFragmentParams(hash);

    const token = hashParams.get(PREVIEW_TOKEN_PARAM);
    if (!token) return null;

    const refreshToken = hashParams.get(PREVIEW_REFRESH_TOKEN_PARAM);

    return {
      token,
      ...(refreshToken ? { refreshToken } : {}),
    };
  } catch {
    return null;
  }
}

// Pede a sessão à janela pai. O targetOrigin é fixado na origin do Mitra, e a
// resposta só é aceita se vier dessa origin e da janela pai exata.
function requestPreviewLogin(): Promise<PreviewSession> {
  return new Promise((resolve, reject) => {
    const mitraOrigin = new URL(AUTH_URL).origin;

    const timer = setTimeout(() => {
      cleanup();
      reject(new Error('Sem resposta do Mitra'));
    }, PREVIEW_LOGIN_TIMEOUT_MS);

    function onMessage(event: MessageEvent) {
      if (event.origin !== mitraOrigin) return;
      if (event.source !== window.parent) return;
      if (event.data?.type !== PREVIEW_LOGIN_RESPONSE_TYPE) return;
      cleanup();

      const { baseURL, token, refreshToken } = event.data.session ?? {};
      if (!baseURL || !token) {
        reject(new Error(event.data.error || 'Mitra não retornou a sessão'));
        return;
      }

      resolve({
        baseURL,
        token,
        ...(refreshToken ? { refreshToken } : {}),
      });
    }

    function cleanup() {
      window.removeEventListener('message', onMessage);
      clearTimeout(timer);
    }

    window.addEventListener('message', onMessage);
    window.parent.postMessage(
      { type: PREVIEW_LOGIN_REQUEST_TYPE, projectId: APP_ID },
      mitraOrigin,
    );
  });
}

// Único ponto que entrega a sessão do preview à SDK. setSession devolve false
// quando o token não é deste app, e nesse caso a SDK já limpou o estado local.
function adoptPreviewSession(session: PreviewFragmentSession): boolean {
  return mitra.auth.setSession({
    accessToken: session.token.replace(/^Bearer\s+/i, ''),
    ...(session.refreshToken ? { refreshToken: session.refreshToken } : {}),
  });
}

// Resolve a autenticação ANTES do primeiro render (aguardado no App.tsx):
// true = sessão configurada (app nasce logado), false = segue para o login.
// Persistência, refresh proativo e retry após 401 pertencem ao Platform SDK.
// Roda uma vez por documento: quem garante isso é o initMitra, logo abaixo.
async function boot(): Promise<boolean> {
  await mitra.init();

  const arrivedWithSignInLink = carriesSignInLink();

  try {
    // Cada conclusão termina apenas o fluxo que ela começou e responde null ao
    // que sobrou de outro método, então a ordem entre elas não importa. As três
    // entram porque a tela de login oferece as três: hoje os dois SSO abrem
    // popup e não passam por aqui, mas trocar para 'redirect', que é o que um
    // navegador de celular pede, é uma linha, e o provedor que ficasse de fora
    // viraria uma entrada que começa e nunca termina.
    const redirectUser =
      (await mitra.auth.completeGoogleSignInRedirect()) ??
      (await mitra.auth.completeMicrosoftSignInRedirect()) ??
      (await mitra.auth.completeEmailSignInRedirect());
    if (redirectUser) return true;

    // Link que chegou e não virou sessão, sem ninguém ter recusado nada: é a
    // segunda abertura da mesma mensagem, a abertura em outro navegador ou o
    // pedido que passou dos 10 minutos. Nada foi consumido, então não é falha,
    // mas também não pode ser silêncio: a próxima coisa que a pessoa vê é a
    // tela de login, e uma tela muda depois de um clique parece app que comeu
    // o clique.
    if (arrivedWithSignInLink) signInLinkOutcome = SIGN_IN_LINK_NOT_CLAIMED;
  } catch (error) {
    // O fragmento fica como está. A SDK já tira o '#emailToken=' antes de
    // lançar, aqui o router é o BrowserRouter e não lê o fragmento como rota, e
    // o que sobra nele pode ser do preview ('#previewToken'), que tem a própria
    // limpeza. Apagar o fragmento inteiro só atrapalharia.
    signInLinkOutcome = error;
    return false;
  }

  // O preview pega uma sessão fresca do builder antes de validar a sessão já
  // persistida. O fragmento do endereço vale sempre que estiver presente, com
  // ou sem nome no iframe.
  const fragmentSession = readPreviewSessionFromFragment();
  if (fragmentSession !== null) {
    try {
      // O reload do iframe repete o src, então o fragmento pode trazer um token
      // velho. Ele só vale depois que o checkAuth confirma; se não confirmar, o
      // resto do fluxo segue e, no iframe nomeado, o handshake ainda tem a vez.
      if (adoptPreviewSession(fragmentSession) && (await mitra.auth.checkAuth())) {
        return true;
      }
    } catch {
      // Fragmento que não serve não derruba o fluxo: segue para os fallbacks.
    }
  }

  // O handshake por postMessage só roda no iframe nomeado, que é o builder
  // antigo ainda respondendo.
  if (window.name === PREVIEW_IFRAME_NAME) {
    try {
      adoptPreviewSession(await requestPreviewLogin());
    } catch {
      // A sessão persistida continua sendo o fallback do preview.
    }
  }

  return mitra.auth.checkAuth();
}

let bootPromise: Promise<boolean> | null = null;

// O que fica guardado é a promise, não o resultado. O App.tsx chama isto de um
// useEffect e em dev o StrictMode monta, desmonta e remonta: sem memoizar, as
// duas execuções leriam o mesmo '#emailToken' no mesmo tick e as duas tentariam
// reivindicá-lo. Uma estabeleceria a sessão e a outra levaria MAGIC_LINK_USED, e
// é a segunda que decide a tela, porque a limpeza do primeiro efeito já desligou
// o 'active' dele: a pessoa cairia no login lendo que o link já foi usado,
// estando logada. De quebra, o mitra.init() e o handshake do preview param de
// rodar em duplicata.
export function initMitra(): Promise<boolean> {
  if (bootPromise === null) {
    bootPromise = boot().then(
      (authenticated) => {
        // Saída única do boot, e onde o slot morre: ver signInLinkOutcome.
        if (authenticated) signInLinkOutcome = null;
        return authenticated;
      },
      (error) => {
        // Só rejeita o que corre fora do try do boot: o mitra.init() e o
        // checkAuth final. Nos dois o link de entrada continua intacto, porque
        // quem o gasta está dentro do try e resolve mesmo quando falha. Por
        // isso soltar a memoização aqui devolve a chance de tentar de novo sem
        // risco de reivindicar o mesmo token duas vezes.
        bootPromise = null;
        throw error;
      },
    );
  }

  return bootPromise;
}

export function clearSession(): void {
  mitra.auth.signOut();
}
