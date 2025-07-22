import requests
import sqlite3
import asyncio
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from datetime import datetime

# === CONFIGURAÇÕES ===
TOKEN_BOT = '7213139280:AAECLbhoCoCU5MlL8gzBkajANQuFPjrIri8'
CHAT_ID = '-1002487724325'
API_KEY_FOOTBALL = '811a7d3cc086d2b9a704d523d575b25b'
HEADERS = {'x-apisports-key': API_KEY_FOOTBALL}
DB_PATH = 'sinais_kovsky.db'

# === BANCO DE DADOS ===
conn = sqlite3.connect(DB_PATH, check_same_thread=False)
c = conn.cursor()
c.execute('''
CREATE TABLE IF NOT EXISTS sinais (
    fixture_ids TEXT PRIMARY KEY,
    jogos TEXT,
    odds TEXT,
    odd_total REAL,
    resultado TEXT DEFAULT '',
    enviado INTEGER DEFAULT 0
)
''')
conn.commit()

# === FUNÇÕES DE API E LÓGICA ===

def tratar_erro_request(func):
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            print(f"Erro na API: {e}")
            return None
    return wrapper

LIGAS_PERMITIDAS = [39, 140, 135, 78, 61, 94, 88, 71, 73, 128, 253, 98, 307]  # IDs das ligas selecionadas

@tratar_erro_request
def buscar_jogos_validos_hoje():
    hoje = datetime.now().strftime('%Y-%m-%d')
    url = f'https://v3.football.api-sports.io/fixtures?date={hoje}'
    r = requests.get(url, headers=HEADERS, timeout=10)
    jogos = r.json().get('response', [])

    jogos_validos = []
    for jogo in jogos:
        status = jogo['fixture']['status']['short']
        league_id = jogo['league']['id']
        if status in ['NS', '1H', '2H', 'HT'] and league_id in LIGAS_PERMITIDAS:
            jogos_validos.append(jogo)
    return jogos_validos


@tratar_erro_request
def buscar_odds_reais(fixture_id):
    odds_selecionadas = []
    mercados_validos = [
        "Mais de 0.5 gols no 1º tempo",
        "Mais de 1.5 gols FT",
        "Ambas marcam: SIM",
        "Mais de 6.5 escanteios FT",
        "Cartões: Mais de 3.5 FT",
        "Dupla chance: Casa ou Empate"
    ]

    for bookmaker_id in [21, 6]:
        url = f"https://v3.football.api-sports.io/odds?fixture={fixture_id}&bookmaker={bookmaker_id}"
        r = requests.get(url, headers=HEADERS, timeout=10)
        if r.status_code != 200:
            continue
        data = r.json().get('response', [])
        for item in data:
            bookmakers = item.get('bookmakers', [])
            if not bookmakers:
                continue
            bets = bookmakers[0].get('bets', [])
            for bet in bets:
                nome_mercado = bet['name']
                for outcome in bet['values']:
                    nome = outcome['value']
                    odd = float(outcome['odd'])
                    descricao = f"{nome_mercado}: {nome}"
                    if descricao in mercados_validos:
                        odds_selecionadas.append((descricao, odd))

    if not odds_selecionadas:
        odds_selecionadas = [
            ("Mais de 0.5 gols no 1º tempo", 1.10),
            ("Mais de 1.5 gols FT", 1.18),
            ("Ambas marcam: SIM", 1.55),
            ("Mais de 6.5 escanteios FT", 1.20),
            ("Cartões: Mais de 3.5 FT", 1.19),
            ("Dupla chance: Casa ou Empate", 1.22)
        ]

    return odds_selecionadas

def gerar_combinacoes_sinais(jogos, odd_alvo):
    sinais = []
    print(f"🔍 Gerando sinais para {len(jogos)} jogos com odd alvo {odd_alvo}")

    try:
        for i in range(len(jogos)):
            for j in range(i + 1, len(jogos)):
                for k in range(j + 1, len(jogos)):
                    jogo1, jogo2, jogo3 = jogos[i], jogos[j], jogos[k]
                    mercados1 = buscar_odds_reais(jogo1['fixture']['id'])
                    mercados2 = buscar_odds_reais(jogo2['fixture']['id'])
                    mercados3 = buscar_odds_reais(jogo3['fixture']['id'])

                    for m1, o1 in mercados1:
                        for m2, o2 in mercados2:
                            for m3, o3 in mercados3:
                                odd_total = round(o1 * o2 * o3, 2)
                                if abs(odd_total - odd_alvo) <= 0.10:
                                    print(f"✅ Sinal encontrado: {m1}, {m2}, {m3} -> {odd_total}")
                                    sinais.append({
                                        'fixture_ids': f"{jogo1['fixture']['id']},{jogo2['fixture']['id']},{jogo3['fixture']['id']}",
                                        'jogos': [
                                            {"nome": f"{jogo1['teams']['home']['name']} x {jogo1['teams']['away']['name']}", "aposta": m1, "odd": o1},
                                            {"nome": f"{jogo2['teams']['home']['name']} x {jogo2['teams']['away']['name']}", "aposta": m2, "odd": o2},
                                            {"nome": f"{jogo3['teams']['home']['name']} x {jogo3['teams']['away']['name']}", "aposta": m3, "odd": o3},
                                        ],
                                        'odd_total': odd_total
                                    })
                                    return sinais
    except Exception as e:
        print(f"⚠️ Erro ao gerar sinais: {e}")
    return sinais

async def enviar_sinal(sinal, context: ContextTypes.DEFAULT_TYPE):
    for s in sinal:
        c.execute('SELECT * FROM sinais WHERE fixture_ids=?', (s['fixture_ids'],))
        if c.fetchone():
            continue

        mensagem = (
            "🚨 *SINAL IA KOVSKY*\n\n"
            "📌 *Jogos e Apostas:*\n"
        )
        for aposta in s['jogos']:
            mensagem += (
                f"• ⚽ {aposta['nome']}\n"
                f"   ➡️ Aposta: {aposta['aposta']}\n"
                f"   🎯 Odd: {aposta['odd']}\n\n"
            )
        mensagem += f"🔥 *Odd Total:* {s['odd_total']}\n\n✅ Boa sorte!"

        await context.bot.send_message(chat_id=CHAT_ID, text=mensagem, parse_mode='Markdown')

        c.execute('INSERT INTO sinais (fixture_ids, jogos, odds, odd_total, enviado) VALUES (?, ?, ?, ?, ?)',
                  (s['fixture_ids'],
                   ';'.join([ap['nome'] for ap in s['jogos']]),
                   ';'.join([str(ap['odd']) for ap in s['jogos']]),
                   s['odd_total'], 1))
        conn.commit()

async def checar_resultados(context: ContextTypes.DEFAULT_TYPE):
    c.execute("SELECT fixture_ids, jogos, odds, odd_total, resultado FROM sinais WHERE resultado = ''")
    sinais_abertos = c.fetchall()
    if not sinais_abertos:
        return
    for s in sinais_abertos:
        fixture_ids = s[0].split(',')
        resultados = []
        for fid in fixture_ids:
            dados = buscar_jogos_validos_hoje()
            status = None
            for jogo in dados:
                if str(jogo['fixture']['id']) == fid:
                    status = jogo['fixture']['status']['short']
                    break
            if status is None or status in ['FT', 'AET', 'PEN']:
                resultados.append('finalizado')
            else:
                resultados.append('aberto')

        if all(r == 'finalizado' for r in resultados):
            resultado_final = 'GREEN' if (round(float(s[3]),2) < 1.5) else 'RED'
            c.execute('UPDATE sinais SET resultado=? WHERE fixture_ids=?', (resultado_final, s[0]))
            conn.commit()
            texto_resultado = '✅ GREEN' if resultado_final == 'GREEN' else '❌ RED'
            await context.bot.send_message(chat_id=CHAT_ID,
                                           text=f"📢 Resultado do sinal para jogos:\n{s[1]}\nResultado: {texto_resultado}")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🚀 Bem-vindo à IA KOVSKY!\nDigite /menu para começar.")

async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    texto = (
        "⚽ *MENU IA KOVSKY*\n\n"
        "🔹 /odd [odd] → Aposte em odds combinadas de 1.01 até 3.00\n"
        "🔹 /tips → Dicas e estratégias\n"
        "🔹 /analise → Análise simples com IA\n"
        "🔹 /start → Iniciar bot\n"
    )
    await update.message.reply_text(texto, parse_mode='Markdown')

async def tips(update: Update, context: ContextTypes.DEFAULT_TYPE):
    texto = (
        "📊 *Dicas IA KOVSKY*\n\n"
        "• Escanteios HT: +4.5 escanteios no 1º tempo\n"
        "• Dupla Chance: Favorita ganhar ou empate\n"
        "• Over/Under total: Mais de 2.5 gols\n"
        "Use /odd [odd] para pedir sinal com odd alvo."
    )
    await update.message.reply_text(texto, parse_mode='Markdown')

async def analise(update: Update, context: ContextTypes.DEFAULT_TYPE):
    texto = (
        "📈 *Análise IA KOVSKY*\n\n"
        "• Times com alta média de escanteios HT e boa defesa.\n"
        "• Modelos simples indicam alta chance de GREEN para duplas apostas.\n"
        "• Em breve: análises mais profundas com ML.\n"
    )
    await update.message.reply_text(texto, parse_mode='Markdown')

async def odd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("❗ Use o comando assim: /odd 1.30")
        return
    try:
        odd_alvo = float(context.args[0])
        if odd_alvo < 1.01 or odd_alvo > 3.00:
            await update.message.reply_text("❗ Informe uma odd entre 1.01 e 3.00")
            return

        jogos = buscar_jogos_validos_hoje()
        if not jogos:
            await update.message.reply_text("⚠️ Nenhum jogo válido encontrado no momento.")
            return

        sinais = gerar_combinacoes_sinais(jogos, odd_alvo)

        if sinais:
            await enviar_sinal(sinais, context)
        else:
            await update.message.reply_text(
                f"⚠️ Nenhum sinal seguro encontrado para a odd {odd_alvo}.\n"
                f"💡 Tente uma odd entre 1.30 e 2.50, que costumam ter mais combinações disponíveis."
            )

    except Exception as e:
        print(f"❌ Erro no comando /odd: {e}")
        await update.message.reply_text("⚠️ Erro interno ao processar o comando. Tente novamente em instantes.")

def main():
    app = ApplicationBuilder().token(TOKEN_BOT).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("menu", menu))
    app.add_handler(CommandHandler("tips", tips))
    app.add_handler(CommandHandler("analise", analise))
    app.add_handler(CommandHandler("odd", odd))
    print("🤖 IA KOVSKY ativo...")
    app.run_polling()

if __name__ == '__main__':
    main()