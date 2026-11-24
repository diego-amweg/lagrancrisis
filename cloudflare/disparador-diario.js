// Disparador externo del Diario (Cloudflare Worker con horarios).
//
// Por qué existe: desde el 22/11/2026 GitHub no largó nunca los horarios propios de
// "Diario - edición diaria". Este Worker le pide a GitHub que corra el proceso a las
// mismas horas. Si los horarios de GitHub vuelven a andar, no pasa nada: la segunda
// corrida ve que la edición ya está publicada y no hace nada.
//
// Configuración en Cloudflare (Workers & Pages > este Worker > Settings):
// - Secreto GITHUB_TOKEN: token de GitHub con permiso "Actions: Read and write"
//   solo sobre diego-amweg/lagrancrisis.
// - Cron Triggers (hora UTC): 12 8 * * *   13 10 * * *   13 13 * * *
//   (05:12, 07:13 y 10:13 de Argentina).

const REPO = "diego-amweg/lagrancrisis";
const WORKFLOW = "diario.yml";
const INTENTO_POR_HORARIO = { "12 8 * * *": "1", "13 10 * * *": "2", "13 13 * * *": "3" };

async function disparar(intento, token) {
  const respuesta = await fetch(
    `https://api.github.com/repos/${REPO}/actions/workflows/${WORKFLOW}/dispatches`,
    {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
        Accept: "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "diario-lagrancrisis-disparador",
      },
      body: JSON.stringify({ ref: "main", inputs: { intento } }),
    },
  );
  if (respuesta.status !== 204) {
    throw new Error(`GitHub respondió ${respuesta.status}: ${await respuesta.text()}`);
  }
}

export default {
  async scheduled(evento, env) {
    await disparar(INTENTO_POR_HORARIO[evento.cron] || "1", env.GITHUB_TOKEN);
  },
  // Para probar a mano desde el navegador: abrir la dirección del Worker con ?probar=1
  // corre el intento 3: si la edición de hoy ya existe no hace nada; si no, la arma y la publica.
  async fetch(pedido, env) {
    const url = new URL(pedido.url);
    if (url.searchParams.get("probar") !== "1") {
      return new Response("Disparador del Diario. Agregá ?probar=1 para lanzar una corrida.");
    }
    try {
      await disparar("3", env.GITHUB_TOKEN);
      return new Response("Listo: GitHub recibió el pedido. Mirá la pestaña Actions.");
    } catch (e) {
      return new Response(`No se pudo: ${e.message}`, { status: 500 });
    }
  },
};
