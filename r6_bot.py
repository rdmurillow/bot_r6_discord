import discord
from discord.ext import commands
from discord.ui import Button, View, Select
import random
import os
import asyncio
import logging
import sqlite3
from typing import Optional, Dict, List, Tuple
from datetime import datetime, timedelta
import aiohttp
from io import BytesIO
import pytz
from dotenv import load_dotenv
import re

# Carregar variáveis de ambiente
load_dotenv()

# Configuração do token
TOKEN = os.getenv("DISCORD_BOT_TOKEN")

# Configuração de logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger('discord_bot')

# Configuração das intents
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

# Criando a instância do bot
bot = commands.Bot(command_prefix='!', intents=intents)

# --- Variáveis e Constantes ---

# Sistema de Ranks do R6
RANKS = {
    "COBRE": {"emoji": "🥉", "valor": 0},
    "BRONZE": {"emoji": "🔶", "valor": 1000},
    "PRATA": {"emoji": "🔷", "valor": 2000},
    "OURO": {"emoji": "🥇", "valor": 3000},
    "PLATINA": {"emoji": "💠", "valor": 4000},
    "ESMERALDA": {"emoji": "💚", "valor": 5000},
    "DIAMANTE": {"emoji": "💎", "valor": 6000},
    "CHAMPION": {"emoji": "🏆", "valor": 7000}
}

# Variáveis globais (simplificadas para o lobby_1)
lobbies = {
    "lobby_1": {
        "jogadores": [],
        "em_andamento": False,
        "sala_partida": None,
        "canal_resultados": None
    }
}
MAX_JOGADORES = 10
TIMEOUT_DURATION = 900  # 15 minutos em segundos

# Lista atualizada de mapas
mapas = [
    "BANK", "BORDER", "CHALET", "CLUBHOUSE", "CONSULATE",
    "KAFE DOSTOYEVSKY", "OREGON", "SKYSCRAPER", "VILLA",
    "NIGHTHAVEN LABS", "LAIR", "OUTBACK", "THEME PARK", "EMERALD PLAINS"
]

# Dicionário para armazenar informações de cada lobby
lobby_info = {
    "lobby_1": {
        "capitao1": None,
        "capitao2": None,
        "mapas_banidos": [],
        "mapa_escolhido": None,
        "ban_view": None,
        "ban_message": None,
        "jogadores_timeout": set()
    }
}

# Canais de administração
categoria_partidas = None
categoria_lobbies = None
canal_resultados = None
canal_boas_vindas = None

# Configuração do banco de dados
DB_PATH = "r6_stats.db"

# --- Funções de Banco de Dados ---

def get_db_connection():
    """Retorna uma nova conexão com o banco de dados."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """Inicializa as tabelas do banco de dados."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Tabela de jogadores
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS jogadores (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        discord_id INTEGER UNIQUE,
        discord_name TEXT,
        r6_nickname TEXT,
        rank TEXT,
        elo INTEGER DEFAULT 0,
        partidas_jogadas INTEGER DEFAULT 0,
        vitorias INTEGER DEFAULT 0,
        derrotas INTEGER DEFAULT 0,
        kills INTEGER DEFAULT 0,
        deaths INTEGER DEFAULT 0,
        kd_ratio REAL DEFAULT 0.0,
        data_registro TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')
    
    # Tabela de partidas
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS partidas (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        lobby_id TEXT,
        mapa TEXT,
        time_vencedor INTEGER,
        data_partida TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')
    
    # Tabela de jogadores por partida
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS partida_jogadores (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        partida_id INTEGER,
        jogador_id INTEGER,
        time INTEGER,
        kills INTEGER DEFAULT 0,
        deaths INTEGER DEFAULT 0,
        resultado TEXT,
        FOREIGN KEY (partida_id) REFERENCES partidas (id),
        FOREIGN KEY (jogador_id) REFERENCES jogadores (id)
    )
    ''')
    
    conn.commit()
    conn.close()

def get_jogador_by_id(discord_id: int) -> Optional[sqlite3.Row]:
    """Busca um jogador pelo ID do Discord."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM jogadores WHERE discord_id = ?", (discord_id,))
    jogador = cursor.fetchone()
    conn.close()
    return jogador

# Inicializar o banco de dados
init_db()

# --- Classes de Views e Modais ---

# View para seleção de rank
class RankSelectView(View):
    def __init__(self, user_id):
        super().__init__(timeout=120)
        self.user_id = user_id
        self.rank = None
    
    @discord.ui.select(
        placeholder="Selecione seu rank",
        options=[
            discord.SelectOption(label="Cobre", emoji="🥉", value="COBRE"),
            discord.SelectOption(label="Bronze", emoji="🔶", value="BRONZE"),
            discord.SelectOption(label="Prata", emoji="🔷", value="PRATA"),
            discord.SelectOption(label="Ouro", emoji="🥇", value="OURO"),
            discord.SelectOption(label="Platina", emoji="💠", value="PLATINA"),
            discord.SelectOption(label="Esmeralda", emoji="💚", value="ESMERALDA"),
            discord.SelectOption(label="Diamante", emoji="💎", value="DIAMANTE"),
            discord.SelectOption(label="Champion", emoji="🏆", value="CHAMPION")
        ]
    )
    async def select_rank(self, interaction: discord.Interaction, select: discord.ui.Select):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Este menu não é para você!", ephemeral=True)
            return
        
        self.rank = select.values[0]
        
        # Salvar rank no banco de dados
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute(
            "UPDATE jogadores SET rank = ?, elo = ? WHERE discord_id = ?",
            (self.rank, RANKS[self.rank]["valor"], self.user_id)
        )
        
        conn.commit()
        conn.close()
        
        await interaction.response.send_message(
            f"Rank {RANKS[self.rank]['emoji']} **{self.rank}** selecionado com sucesso! ✅",
            ephemeral=True
        )
        
        # Enviar mensagem de boas-vindas ao competitivo
        embed = discord.Embed(
            title="🎮 Bem-vindo ao Competitivo de Rainbow Six Siege! 🎮",
            description="Agora você faz parte da nossa comunidade competitiva!",
            color=discord.Color.gold()
        )
        
        embed.add_field(
            name="📋 Regras do Lobby",
            value=(
                "1. Respeite todos os jogadores\n"
                "2. Não utilize hacks ou cheats\n"
                "3. Mantenha a comunicação clara e objetiva\n"
                "4. Aceite o resultado das partidas com esportividade\n"
                "5. Reporte problemas para os administradores"
            ),
            inline=False
        )
        
        embed.add_field(
            name="⚙️ Sistema de Rank (ELO)",
            value=(
                "Seu progresso será acompanhado através do nosso sistema de ELO:\n"
                "• Vitórias: **+25 ELO**\n"
                "• Derrotas: **-10 ELO**\n"
                "• MVP da partida: **+5 ELO bônus** (A ser implementado)"
            ),
            inline=False
        )
        
        embed.set_footer(text="Divirta-se e boa sorte!")
        
        await interaction.followup.send(embed=embed, ephemeral=True)
        self.stop()

# Modal para inserir nick do R6
class NickModal(discord.ui.Modal, title="Registro de Nick do R6"):
    def __init__(self):
        super().__init__()
        self.nickname = None
    
    nick = discord.ui.TextInput(
        label="Seu nick no Rainbow Six Siege",
        placeholder="Ex: R6_ProPlayer123",
        min_length=3,
        max_length=20
    )
    
    async def on_submit(self, interaction: discord.Interaction):
        self.nickname = self.nick.value
        await interaction.response.send_message(
            f"Nick **{self.nickname}** recebido! Prossiga para a seleção de Rank.",
            ephemeral=True
        )
        self.stop()

# View para registro inicial
class RegistroView(View):
    def __init__(self, user_id):
        super().__init__(timeout=300)
        self.user_id = user_id
    
    @discord.ui.button(label="Competitivo R6", style=discord.ButtonStyle.primary, emoji="🎮")
    async def registro_competitivo(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Este menu não é para você!", ephemeral=True)
            return
        
        # Verificar se já está registrado
        jogador = get_jogador_by_id(self.user_id)
        
        if jogador and jogador["r6_nickname"]:
            await interaction.response.send_message(
                "Você já está registrado no sistema competitivo!",
                ephemeral=True
            )
            return
        
        # Modal para inserir nick do R6
        modal = NickModal()
        await interaction.response.send_modal(modal)
        
        # Aguarda o modal ser preenchido
        await modal.wait()
        
        if modal.nickname:
            r6_nickname = modal.nickname
            
            # Salvar no banco de dados
            conn = get_db_connection()
            cursor = conn.cursor()
            
            if jogador:
                cursor.execute(
                    "UPDATE jogadores SET r6_nickname = ? WHERE discord_id = ?",
                    (r6_nickname, self.user_id)
                )
            else:
                cursor.execute(
                    "INSERT INTO jogadores (discord_id, discord_name, r6_nickname) VALUES (?, ?, ?)",
                    (self.user_id, interaction.user.name, r6_nickname)
                )
            
            conn.commit()
            conn.close()
            
            # Pedir para selecionar o rank
            view = RankSelectView(self.user_id)
            await interaction.followup.send(
                f"Nick **{r6_nickname}** registrado! Agora selecione seu rank:",
                view=view,
                ephemeral=True
            )
            
            self.stop()

# Placeholder para o sistema de Ban/Pick de Mapas
class BanMapaButton(Button):
    def __init__(self, mapa: str):
        super().__init__(label=mapa, style=discord.ButtonStyle.secondary)
        self.mapa = mapa

    async def callback(self, interaction: discord.Interaction):
        # Implementação da lógica de banimento (Capitão 1 / Capitão 2)
        await interaction.response.send_message(f"Mapa **{self.mapa}** banido (lógica a ser implementada).", ephemeral=True)

class BanMapaView(View):
    def __init__(self, mapas_disponiveis: List[str]):
        super().__init__(timeout=120)
        for mapa in mapas_disponiveis:
            self.add_item(BanMapaButton(mapa))

# --- Eventos do Bot ---

# Evento quando um membro entra no servidor
@bot.event
async def on_member_join(member):
    if canal_boas_vindas:
        embed = discord.Embed(
            title=f"👋 Bem-vindo(a) ao Servidor, {member.name}!",
            description="Somos uma comunidade dedicada ao **Rainbow Six Siege competitivo**.",
            color=discord.Color.blue()
        )
        
        embed.add_field(
            name="🎮 Para jogar competitivo",
            value="Clique no botão abaixo para se registrar no sistema competitivo.",
            inline=False
        )
        
        embed.add_field(
            name="📊 Estatísticas e Ranking",
            value="Seu progresso será acompanhado com nosso sistema de ELO.",
            inline=False
        )
        
        embed.set_thumbnail(url=member.avatar.url if member.avatar else member.default_avatar.url)
        embed.set_footer(text="Divirta-se e boa sorte nas partidas!")
        
        view = RegistroView(member.id)
        await canal_boas_vindas.send(f"{member.mention}", embed=embed, view=view)

# Evento que confirma que o bot está online
@bot.event
async def on_ready():
    logger.info(f"Bot {bot.user.name} está online!")
    
    # Garantir que o bot está em pelo menos um servidor
    if not bot.guilds:
        logger.error("O bot não está em nenhum servidor.")
        return
        
    # Configurar categorias e canais
    await configurar_canais(bot.guilds[0])
    
    try:
        await bot.tree.sync()
        logger.info("Comandos de aplicação sincronizados.")
    except Exception as e:
        logger.error(f"Erro ao sincronizar comandos: {e}")


async def configurar_canais(guild: discord.Guild):
    """Configura os canais e categorias necessários na Guilda (Servidor)."""
    global categoria_partidas, categoria_lobbies, canal_resultados, canal_boas_vindas
    
    # 1. Encontrar ou criar categorias
    for categoria in guild.categories:
        if categoria.name == "PARTIDAS":
            categoria_partidas = categoria
        elif categoria.name == "LOBBYS":
            categoria_lobbies = categoria
    
    if not categoria_partidas:
        categoria_partidas = await guild.create_category("PARTIDAS")
    
    if not categoria_lobbies:
        categoria_lobbies = await guild.create_category("LOBBYS")
    
    # 2. Configurar ou criar a categoria RECURSOS e canal de boas-vindas
    recursos_categoria = discord.utils.get(guild.categories, name="RECURSOS")
    
    if not recursos_categoria:
        recursos_categoria = await guild.create_category("RECURSOS")
        
    canal_boas_vindas = discord.utils.get(recursos_categoria.text_channels, name="boas-vindas")
    
    if not canal_boas_vindas:
        canal_boas_vindas = await recursos_categoria.create_text_channel("boas-vindas")
        
        # Mensagem de boas-vindas inicial (apenas se o canal for novo)
        embed = discord.Embed(
            title="🎮 Bem-vindo ao Servidor de Rainbow Six Siege Competitivo!",
            description="Este é o hub central para competições de R6. Clique no botão de **registro** para participar!",
            color=discord.Color.gold()
        )
        await canal_boas_vindas.send(embed=embed)
    
    # 3. Encontrar ou criar canal de resultados
    canal_resultados = discord.utils.get(categoria_partidas.text_channels, name="resultados-partidas")
    
    if not canal_resultados:
        canal_resultados = await categoria_partidas.create_text_channel("resultados-partidas")
        
        # Configurar permissões do canal de resultados (somente admins/bot podem ver)
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True)
        }
        
        for role in guild.roles:
            if role.permissions.administrator:
                overwrites[role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
        
        await canal_resultados.edit(overwrites=overwrites)

# --- Comandos do Bot ---

# Comando para registro manual
@bot.command(name='registrar')
async def registrar(ctx):
    """Comando para se registrar no sistema competitivo"""
    view = RegistroView(ctx.author.id)
    await ctx.send(
        f"{ctx.author.mention}, clique para se registrar no sistema competitivo:",
        view=view
    )

# Comando para ver estatísticas
@bot.command(name='estatisticas')
async def estatisticas(ctx, membro: Optional[discord.Member] = None):
    """Mostra as estatísticas de um jogador"""
    target = membro or ctx.author
    
    jogador = get_jogador_by_id(target.id)
    
    if not jogador or not jogador["r6_nickname"]:
        await ctx.send(f"{target.mention} não está registrado no sistema competitivo!")
        return
    
    # Calcular KD ratio e Win Rate
    kd = jogador["kd_ratio"]
    partidas = jogador["partidas_jogadas"]
    win_rate = (jogador["vitorias"] / partidas * 100) if partidas > 0 else 0
    
    embed = discord.Embed(
        title=f"📊 Estatísticas de {jogador['r6_nickname']}",
        color=discord.Color.blue()
    )
    
    rank_data = RANKS.get(jogador['rank'], {"emoji": "❓", "valor": 0})
    
    embed.add_field(name="Rank", value=f"{rank_data.get('emoji', '')} **{jogador['rank']}**", inline=True)
    embed.add_field(name="ELO", value=str(jogador["elo"]), inline=True)
    embed.add_field(name="Partidas", value=str(partidas), inline=True)
    
    embed.add_field(name="Vitórias", value=str(jogador["vitorias"]), inline=True)
    embed.add_field(name="Derrotas", value=str(jogador["derrotas"]), inline=True)
    embed.add_field(name="Win Rate", value=f"**{win_rate:.1f}%**", inline=True)
    
    embed.add_field(name="Kills", value=str(jogador["kills"]), inline=True)
    embed.add_field(name="Deaths", value=str(jogador["deaths"]), inline=True)
    embed.add_field(name="K/D Ratio", value=f"**{kd:.2f}**", inline=True)
    
    embed.set_thumbnail(url=target.avatar.url if target.avatar else target.default_avatar.url)
    await ctx.send(embed=embed)

# Comando para ver ranking
@bot.command(name='ranking')
async def ranking(ctx):
    """Mostra o ranking dos jogadores"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM jogadores WHERE elo > 0 AND partidas_jogadas > 0 ORDER BY elo DESC, kd_ratio DESC LIMIT 10")
    top_jogadores = cursor.fetchall()
    conn.close()
    
    embed = discord.Embed(
        title="🏆 Ranking dos Jogadores (Top 10 ELO)",
        color=discord.Color.gold()
    )
    
    if not top_jogadores:
        embed.description = "Nenhum jogador no ranking ainda. Jogue uma partida!"
    else:
        for i, jogador in enumerate(top_jogadores):
            rank_emoji = RANKS.get(jogador["rank"], {}).get("emoji", "")
            win_rate = (jogador['vitorias']/jogador['partidas_jogadas']*100) if jogador['partidas_jogadas'] > 0 else 0
            
            embed.add_field(
                name=f"#{i+1}. {jogador['r6_nickname']} {rank_emoji}",
                value=f"**ELO:** {jogador['elo']} | **K/D:** {jogador['kd_ratio']:.2f} | **W/R:** {win_rate:.1f}%",
                inline=False
            )
    
    await ctx.send(embed=embed)

# Função para processar imagem de resultados (simulado)
async def processar_resultado_imagem(anexo, lobby_id):
    """Função simulada para processar imagem de resultados e extrair dados."""
    
    # Em um cenário real, você usaria OCR (Tesseract) ou uma API de visão.
    # A implementação abaixo é um placeholder.
    
    logger.info(f"Simulando processamento da imagem de resultados do {lobby_id}...")
    await asyncio.sleep(2)
    
    # Retorna dados simulados
    return {
        "time_vencedor": random.randint(1, 2),
        "kills": [random.randint(0, 15) for _ in range(10)], # 10 jogadores
        "deaths": [random.randint(0, 15) for _ in range(10)] # 10 jogadores
    }

# Comando para finalizar partida com processamento de imagem
@bot.command()
@commands.has_permissions(administrator=True)
async def finalizar_partida(ctx, lobby_id: str):
    """Finaliza uma partida e atualiza as estatísticas com base no print do resultado."""
    if lobby_id not in lobbies or not lobbies[lobby_id]["em_andamento"]:
        await ctx.send("Partida não encontrada ou não está em andamento!")
        return
    
    if not ctx.message.attachments:
        await ctx.send("Por favor, anexe o print do resultado da partida!")
        return
    
    lobby_data = lobbies[lobby_id]
    anexo = ctx.message.attachments[0]
    
    # Verificar se o lobby está cheio (10 jogadores) para garantir a correta distribuição dos dados simulados.
    if len(lobby_data["jogadores"]) != MAX_JOGADORES:
        await ctx.send(f"Erro: O lobby não tem {MAX_JOGADORES} jogadores. Impossível processar o resultado simulado.")
        return

    # Processar imagem
    await ctx.send("📊 Processando resultado da partida (Simulado)...")
    resultado = await processar_resultado_imagem(anexo, lobby_id)
    
    # Registrar partida no banco de dados
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # Inserir partida
        cursor.execute(
            "INSERT INTO partidas (lobby_id, mapa, time_vencedor) VALUES (?, ?, ?)",
            (lobby_id, lobby_info[lobby_id]["mapa_escolhido"] or "DESCONHECIDO", resultado["time_vencedor"])
        )
        partida_id = cursor.lastrowid
        
        # Atualizar estatísticas dos jogadores
        for i, jogador in enumerate(lobby_data["jogadores"]):
            # Buscar ID do jogador no banco
            cursor.execute("SELECT id, kills, deaths FROM jogadores WHERE discord_id = ?", (jogador.id,))
            jogador_db = cursor.fetchone()
            
            if jogador_db:
                # Dados da partida (índices 0-4 = Time 1, 5-9 = Time 2)
                kills = resultado["kills"][i]
                deaths = resultado["deaths"][i]
                time_jogador = 1 if i < 5 else 2
                resultado_jogador = "VITÓRIA" if time_jogador == resultado["time_vencedor"] else "DERROTA"
                
                # Inserir jogador na partida
                cursor.execute(
                    """INSERT INTO partida_jogadores 
                    (partida_id, jogador_id, time, kills, deaths, resultado) 
                    VALUES (?, ?, ?, ?, ?, ?)""",
                    (partida_id, jogador_db["id"], time_jogador, kills, deaths, resultado_jogador)
                )
                
                # Calcular novos valores
                elo_change = 0
                if resultado_jogador == "VITÓRIA":
                    elo_change = 25
                else:
                    elo_change = -10
                
                total_kills = jogador_db["kills"] + kills
                total_deaths = jogador_db["deaths"] + deaths
                
                # Atualizar estatísticas do jogador
                cursor.execute(
                    """UPDATE jogadores 
                    SET vitorias = vitorias + ?, 
                    derrotas = derrotas + ?, 
                    elo = elo + ?,
                    kills = kills + ?, 
                    deaths = deaths + ?, 
                    kd_ratio = CAST(? AS REAL) / NULLIF(?, 0),
                    partidas_jogadas = partidas_jogadas + 1 
                    WHERE id = ?""",
                    (
                        1 if resultado_jogador == "VITÓRIA" else 0,
                        1 if resultado_jogador == "DERROTA" else 0,
                        elo_change,
                        kills,
                        deaths,
                        total_kills,
                        total_deaths,
                        jogador_db["id"]
                    )
                )
        
        conn.commit()
    except Exception as e:
        conn.rollback()
        await ctx.send(f"Ocorreu um erro ao registrar no banco de dados: {e}")
        logger.error(f"Erro no banco de dados: {e}")
        return
    finally:
        conn.close()
    
    # Salvar print no canal de resultados
    mapa_info = lobby_info[lobby_id]["mapa_escolhido"] or "Não Definido"
    embed = discord.Embed(
        title=f"📋 Resultado da Partida {lobby_id.split('_')[1]}",
        description=f"Partida finalizada em **{datetime.now().strftime('%d/%m/%Y %H:%M')}**\n\n**Mapa:** {mapa_info}",
        color=discord.Color.green()
    )
    
    # Exibir jogadores com resultados simulados
    jogadores_list = []
    for i, jogador in enumerate(lobby_data["jogadores"]):
        time_jogador = 1 if i < 5 else 2
        resultado_jogador = "🏆 VITÓRIA" if time_jogador == resultado["time_vencedor"] else "❌ DERROTA"
        kills = resultado["kills"][i]
        deaths = resultado["deaths"][i]
        jogadores_list.append(f"{jogador.mention} (Time {time_jogador}): {resultado_jogador} | Kills: {kills}, Deaths: {deaths}")
        
    embed.add_field(
        name="Jogadores e Desempenho",
        value="\n".join(jogadores_list),
        inline=False
    )
    
    embed.add_field(
        name="Time Vencedor",
        value=f"**Time {resultado['time_vencedor']}**",
        inline=True
    )
    
    if canal_resultados:
        await canal_resultados.send(embed=embed)
        await canal_resultados.send(file=await anexo.to_file())
    else:
        await ctx.send("Canal de resultados não configurado, mas as estatísticas foram salvas.")
    
    # Fechar sala de partida
    if lobby_data["sala_partida"]:
        await lobby_data["sala_partida"].delete()
    
    # Limpar dados do lobby
    lobby_data["jogadores"] = []
    lobby_data["em_andamento"] = False
    lobby_data["sala_partida"] = None
    
    lobby_info[lobby_id] = {
        "capitao1": None,
        "capitao2": None,
        "mapas_banidos": [],
        "mapa_escolhido": None,
        "ban_view": None,
        "ban_message": None,
        "jogadores_timeout": set()
    }
    
    await ctx.send(f"✅ Partida {lobby_id.split('_')[1]} finalizada e estatísticas atualizadas!")

# Inicia o bot
if __name__ == "__main__":
    if not TOKEN:
        logger.error("Token do bot não encontrado! O bot não pode ser iniciado.")
    else:
        bot.run(TOKEN)
