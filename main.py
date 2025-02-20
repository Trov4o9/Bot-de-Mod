import discord
from discord.ext import commands
import sqlite3
import datetime
from discord.ui import View, Button, Modal, TextInput, button
from discord import app_commands
from typing import Optional
import pytz
import re
import os
import time
import random

# Verificar se a tabela existe
db = sqlite3.connect('tickets.db')
cursor = db.cursor()
cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='tickets';")
table_exists = cursor.fetchone()

if table_exists:
    print("✅ A tabela 'tickets' existe no banco de dados.")
else:
    print("❌ A tabela 'tickets' não foi encontrada. Verifique novamente.")

db.close()

# Configuração inicial
intents = discord.Intents.default()
intents.messages = True
intents.message_content = True

bot = commands.Bot(command_prefix='!', intents=intents)

# Conectar ao banco de dados SQLite
db = sqlite3.connect('srdark_coins.db')
cursor = db.cursor()

# Criar tabela para armazenar moedas, se não existir
cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    balance INTEGER DEFAULT 0
)
""")
db.commit()


# Evento: Quando uma mensagem é enviada, armazena no banco de dados
@bot.event
async def on_message(message):
    if message.author.bot:
        return

    # Salva a mensagem no banco de dados
    cursor.execute('''
        INSERT INTO mensagens (user_id, mensagem)
        VALUES (?, ?)
    ''', (message.author.id, message.content))
    conn.commit()

    await bot.process_commands(message)

# Comando para adicionar moedas
@bot.command()
async def add(ctx, user: discord.Member, amount: int):
    if amount <= 0:
        await ctx.send("A quantidade deve ser maior que zero!")
        return

    # Verificar se o usuário já existe no banco
    cursor.execute("SELECT * FROM users WHERE id = ?", (user.id,))
    result = cursor.fetchone()
    if result:
        cursor.execute("UPDATE users SET balance = balance + ? WHERE id = ?", (amount, user.id))
    else:
        cursor.execute("INSERT INTO users (id, balance) VALUES (?, ?)", (user.id, amount))
    db.commit()
    await ctx.send(f"{amount} moedas adicionadas para {user.mention}!")
    await ctx.send(f"{amount} moedas acrecentadas ao jogador {user.mention} !")

# Comando para verificar saldo
@bot.command()
async def balance(ctx, user: discord.Member = None):
    user = user or ctx.author  # Se nenhum usuário for especificado, usar o autor da mensagem
    cursor.execute("SELECT balance FROM users WHERE id = ?", (user.id,))
    result = cursor.fetchone()
    if result:
        await ctx.send(f"{user.mention} tem {result[0]} moedas!")
    else:
        await ctx.send(f"{user.mention} ainda não tem moedas.")

# Comando para transferir moedas
@bot.command()
async def transfer(ctx, user: discord.Member, amount: int):
    if amount <= 0:
        await ctx.send("A quantidade deve ser maior que zero!")
        return

    # Verificar se o autor tem saldo suficiente
    cursor.execute("SELECT balance FROM users WHERE id = ?", (ctx.author.id,))
    author_balance = cursor.fetchone()
    if not author_balance or author_balance[0] < amount:
        await ctx.send("Você não tem moedas suficientes!")
        return

    # Atualizar saldos
    cursor.execute("UPDATE users SET balance = balance - ? WHERE id = ?", (amount, ctx.author.id))
    cursor.execute("SELECT * FROM users WHERE id = ?", (user.id,))
    if cursor.fetchone():
        cursor.execute("UPDATE users SET balance = balance + ? WHERE id = ?", (amount, user.id))
    else:
        cursor.execute("INSERT INTO users (id, balance) VALUES (?, ?)", (user.id, amount))
    db.commit()
    await ctx.send(f"{ctx.author.mention} transferiu {amount} moedas para {user.mention}!")

# Banco de dados
db = sqlite3.connect('tickets.db')
cursor = db.cursor()

# Criação da tabela de tickets (se não existir)
cursor.execute("""
CREATE TABLE IF NOT EXISTS tickets (
    user_id INTEGER,
    status TEXT,
    staff_id INTEGER DEFAULT NULL,
    closed_at TEXT DEFAULT NULL,
    close_reason TEXT DEFAULT NULL
)
""")

db.commit()

# Criação da tabela de mensagens (opcional, usada no desempenho)
cursor.execute("""
CREATE TABLE IF NOT EXISTS mensagens (
    user_id INTEGER,
    timestamp TEXT
)
""")
db.commit()


# Dropdown para selecionar o tipo de ticket
class Dropdown(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(value="atendimento", label="Atendimento", emoji="📨"),
            discord.SelectOption(value="denuncia", label="Denúncia", emoji="🚨"),
        ]
        super().__init__(
            placeholder="Selecione uma opção...",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="persistent_view:dropdown_help"
        )

    async def callback(self, interaction: discord.Interaction):
        if self.values[0] == "atendimento":
            await interaction.response.send_message("Gostaria de abrir um ticket?", ephemeral=True, view=CreateTicketView())
        elif self.values[0] == "denuncia":
            await interaction.response.send_message("Gostaria de abrir um ticket de denúncia?", ephemeral=True, view=CreateTicketView(ticket_type="denuncia"))


class DropdownView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(Dropdown())


# Modal para fechar ticket
class CloseTicketModal(discord.ui.Modal, title="Fechar Ticket"):
    motivo = discord.ui.TextInput(
        label="Motivo do fechamento",
        style=discord.TextStyle.paragraph,
        required=False,
        placeholder="Insira um motivo (opcional)"
    )

    async def on_submit(self, interaction: discord.Interaction):
        motivo = self.motivo.value or "Nenhum motivo fornecido"
        await interaction.response.send_message("Ticket fechado com sucesso!", ephemeral=True)
        await interaction.channel.edit(archived=True, locked=True)

        # Atualiza o ticket no banco de dados
        cursor.execute(
            "UPDATE tickets SET status = 'closed', staff_id = ?, closed_at = ?, close_reason = ? WHERE user_id = ? AND status = 'open'",
            (interaction.user.id, datetime.now().strftime('%Y-%m-%d %H:%M:%S'), motivo, interaction.channel.name.split(" ")[1].strip("()"))
        )
        db.commit()

        # Log no canal de desempenho
        log_channel = interaction.guild.get_channel(log_channel_id)
        if log_channel:
            embed = discord.Embed(title="Ticket Fechado", color=discord.Color.red())
            embed.add_field(name="Usuário", value=interaction.user.mention, inline=True)
            embed.add_field(name="Motivo", value=motivo, inline=False)
            embed.timestamp = interaction.created_at
            await log_channel.send(embed=embed)


# Botão Painel Staff
class StaffPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Painel Staff", style=discord.ButtonStyle.grey, emoji="🛠️", custom_id="staff_panel")
    async def staff_panel(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ **Apenas administradores podem acessar o Painel Staff!**", ephemeral=True)
            return
        
        embed = discord.Embed(
            title="🛠️ Painel Staff",
            description=(
                "**Bem-vindo ao Painel Staff!**\n\n"
                "🔹 **Reivindicar Ticket:** Assuma o ticket imediatamente, mesmo que outro atendente esteja no comando.\n"
                "🔹 **Intervir no Ticket:** Indique que houve um erro no atendimento e assuma a responsabilidade.\n\n"
                "Use os botões abaixo para executar as ações desejadas."
            ),
            color=0x383838
        )
        embed.set_footer(text="Apenas você pode ver este painel.")
        
        # Resposta com embed diretamente aqui
        await interaction.response.send_message(embed=embed, view=StaffOptionsView(), ephemeral=True)


# Botões dentro do Painel Staff
class StaffOptionsView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Reivindicar", style=discord.ButtonStyle.success, emoji="👤", custom_id="claim_ticket")
    async def claim_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ **Apenas administradores podem reivindicar tickets!**", ephemeral=True)
            return

        conn = sqlite3.connect('tickets.db')
        cursor = db.cursor()
        cursor.execute(
            "UPDATE tickets SET staff_id = ? WHERE status = 'open' AND user_id = ?",
            (interaction.user.id, interaction.channel.name.split(" ")[1].strip("()"))
        )
        db.commit()
        
        await interaction.response.send_message(f"✅ **{interaction.user.mention} reivindicou este ticket com sucesso!**", ephemeral=False)

    @discord.ui.button(label="Intervir", style=discord.ButtonStyle.danger, emoji="⚠️", custom_id="intervene_ticket")
    async def intervene_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ **Apenas administradores podem intervir em tickets!**", ephemeral=True)
            return
        
        await interaction.response.send_message(
            f"⚠️ **{interaction.user.mention} interveio neste ticket. Um administrador superior está assumindo.**", ephemeral=False
        )
      
# Conexão com o banco de dados resumos.db
conn = sqlite3.connect('resumos.db')
cursor = conn.cursor()
cursor.execute('''CREATE TABLE IF NOT EXISTS resumos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    helper_id INTEGER,
    ticket_id INTEGER,
    ticket_nome TEXT,
    resumo TEXT,
    data TEXT
)''')
conn.commit()

@bot.tree.command(name="arquivos", description="Acesse resumos de tickets salvos.")
@app_commands.describe(senha="Senha do comando")
async def arquivos(interaction: discord.Interaction, senha: str):
    if senha != token_senha:
        await interaction.response.send_message("❌ Senha incorreta!", ephemeral=True)
        return

    view = ResumoView()
    await interaction.response.send_message("📂 **Selecione um ticket para ver o resumo:**", view=view, ephemeral=True)

class HelperModal(discord.ui.Modal, title="Resumo do Atendimento"):
    resumo = discord.ui.TextInput(label="Resumo do Atendimento", style=discord.TextStyle.paragraph, required=True)

    async def on_submit(self, interaction: discord.Interaction):
        ticket_id = interaction.channel.id
        ticket_nome = interaction.channel.name
        helper_id = interaction.user.id
        data = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        resumo = self.resumo.value

        conn = sqlite3.connect('resumos.db')
        cursor = conn.cursor()
        cursor.execute('INSERT INTO resumos (helper_id, ticket_id, ticket_nome, resumo, data) VALUES (?, ?, ?, ?, ?)',
                       (helper_id, ticket_id, ticket_nome, resumo, data))
        conn.commit()
        conn.close()

        await interaction.response.send_message(f"✅ Resumo salvo com sucesso! Obrigado, {interaction.user.mention}.", ephemeral=True)


# Botão para Resumir Atendimento
class HelperSummaryView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Resumir Atendimento", style=discord.ButtonStyle.grey, emoji="📝", custom_id="resumir_atendimento")
    async def resumir_atendimento(self, interaction: discord.Interaction, button: discord.ui.Button):
        role_manager_ticket = discord.utils.get(interaction.guild.roles, id=id_cargo_manager_ticket)
        if role_manager_ticket not in interaction.user.roles:
            await interaction.response.send_message("❌ **Apenas membros com o cargo Manager Ticket podem resumir o atendimento!**", ephemeral=True)
            return

        await interaction.response.send_modal(HelperModal())



id_cargo_manager_ticket = 1310322685468868690

# Adicionando Painel Staff ao TicketManagementView
class TicketManagementView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Fechar Ticket", style=discord.ButtonStyle.grey, emoji="🔒")
    async def close_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        if f"{interaction.user.id}" in interaction.channel.name or any(
            role.id == id_cargo_atendente for role in interaction.user.roles
        ):
            await interaction.response.send_modal(CloseTicketModal())

    @discord.ui.button(label="Assumir Ticket", style=discord.ButtonStyle.grey, emoji="👤")
    async def claim_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        if any(role.id == id_cargo_atendente for role in interaction.user.roles):
            await interaction.response.send_message(
                f"{interaction.user.mention} assumiu o ticket!", ephemeral=False
            )
            conn = sqlite3.connect('tickets.db')
            cursor = db.cursor()
            cursor.execute(
                "UPDATE tickets SET staff_id = ? WHERE status = 'open' AND user_id = ?",
                (interaction.user.id, interaction.channel.name.split(" ")[1].strip("()"))
            )
            db.commit()
          

    @discord.ui.button(label="Painel Staff", style=discord.ButtonStyle.grey, emoji="🛠️", custom_id="staff_panel_main")
    async def staff_panel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.guild_permissions.administrator:
            # Responde diretamente com o painel ao clicar no botão
            staff_view = StaffPanelView()
            await interaction.response.send_message(embed=None, view=staff_view, ephemeral=True)
        else:
            await interaction.response.send_message("❌ **Apenas administradores podem acessar o Painel Staff!**", ephemeral=True)
          
    @discord.ui.button(label="Painel Helper", style=discord.ButtonStyle.grey, emoji="🛠️", custom_id="helper_panel")
    async def helper_panel(self, interaction: discord.Interaction, button: discord.ui.Button):
        role_manager_ticket = discord.utils.get(interaction.guild.roles, id=id_cargo_manager_ticket)  # ID do cargo

        if role_manager_ticket not in interaction.user.roles:
            await interaction.response.send_message("❌ **Apenas membros com o cargo Manager Ticket podem acessar o Painel Helper!**", ephemeral=True)
            return

        embed = discord.Embed(
            title="🛠️ Painel Helper",
            description=(
                "**Bem-vindo ao Painel Helper!**\n\n"
                "🔹 **Objetivo:** Auxiliar no atendimento e garantir qualidade.\n"
                "🔹 **Resumir Atendimento:** Ao final, resuma o caso antes de fechar o ticket."
            ),
            color=0x4B0082
        )
        embed.set_footer(text="Apenas você pode ver este painel.")

        await interaction.response.send_message(embed=embed, view=HelperSummaryView(), ephemeral=True)

# Comando para acessar os resumos
token_senha = "Wasd2012"

class ResumoSelect(discord.ui.Select):
    def __init__(self, tickets):
        options = [discord.SelectOption(label=ticket[0], value=str(ticket[1])) for ticket in tickets]
        super().__init__(placeholder="Selecione um ticket", options=options)

    async def callback(self, interaction: discord.Interaction):
        conn = sqlite3.connect('resumos.db')
        cursor = conn.cursor()
        cursor.execute('SELECT resumo FROM resumos WHERE ticket_id = ?', (self.values[0],))
        resumo = cursor.fetchone()
        conn.close()

        if resumo:
            await interaction.response.send_message(f"📋 **Resumo do Ticket:** {resumo[0]}", ephemeral=True)
        else:
            await interaction.response.send_message("❌ Resumo não encontrado.", ephemeral=True)

class ResumoView(discord.ui.View):
    def __init__(self):
        super().__init__()
        conn = sqlite3.connect('resumos.db')
        cursor = conn.cursor()
        cursor.execute('SELECT ticket_nome, ticket_id FROM resumos')
        tickets = cursor.fetchall()
        conn.close()

        if tickets:
            self.add_item(ResumoSelect(tickets))


# View para criar um ticket
class CreateTicketView(discord.ui.View):
    def __init__(self, ticket_type="atendimento"):
        super().__init__(timeout=300)
        self.ticket_type = ticket_type

    @discord.ui.button(label="Abrir Ticket", style=discord.ButtonStyle.green, emoji="➕")
    async def create_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        ticket_name = (
            f"denuncia-{interaction.user.name} ({interaction.user.id})"
            if self.ticket_type == "denuncia"
            else f"{interaction.user.name} ({interaction.user.id})"
        )
        ticket = await interaction.channel.create_thread(
            name=ticket_name,
            auto_archive_duration=10080
        )
        await ticket.edit(invitable=False)


        db = sqlite3.connect('tickets.db')
        cursor = db.cursor()
      
        cursor.execute("INSERT INTO tickets (user_id, status) VALUES (?, ?)", (interaction.user.id, "open"))
        db.commit()

        embed = discord.Embed(
            title="Bem-Vindo(a) ao seu ticket! 🔔",
            description=(
                f"📩 **|** {interaction.user.mention} seu ticket foi criado! "
                "Envie as informações necessárias e aguarde atendimento.\n\n"
                "Os tickest são privados, **apenas nossos staffs tem acesso**, nosso servidor zela por sua privacidade!\n\n"
                "**sinta-se livre para dizer o que precisa!**"
            ),
            color=0x383838
        )
      
        embed.set_image(url="https://www.imagensanimadas.com/data/media/562/linha-imagem-animada-0446.gif")

        embed.set_footer(text="*Desenvolvedores: TrovãoAzul e Aki")

        # Adicionando miniatura
        embed.set_thumbnail(url="https://www.tibiawiki.com.br/images/c/c3/Tibiapedia.gif")      

        await ticket.send(f"<@&{id_cargo_atendente}>", embed=embed, view=TicketManagementView())
        await interaction.response.send_message(f"Seu ticket foi criado: {ticket.mention}", ephemeral=True)


@bot.tree.command(name="setup", description="Setup")
@commands.has_permissions(manage_guild=True)
async def setup(interaction: discord.Interaction):
    embed = discord.Embed(
        title="Central de ticks SrDark!!!",
        description=(
            "**Quando posso abrir um ticket?**\n\n"
            "**• Reclamações**\n"
            "**• Denúncias**\n"
            "**• Sugestões**\n\n"
            "**Regras:**\n\n"
            "**• Quando abrir um ticket, fale o que quer em até 10 minutos ou o ticket será fechado.**\n"
            "**• Abrir tickets sem motivo resultará em um mute sem aviso prévio.**"
        ),
        color=discord.Color.yellow()
    )

    embed.set_image(url="https://discord.do/wp-content/uploads/2024/12/SrDark-Contas-Blox-Fruits.jpg")

    embed.set_footer(text="*Desenvolvedores: TrovãoAzul e Aki")

    # Adicionando miniatura
    embed.set_thumbnail(url="https://discord.do/wp-content/uploads/2024/08/SrDark-2-Legends-Blox-Fruits-Trading-Server.jpg")
    await interaction.response.send_message(embed=embed, view=DropdownView())


      
conn = sqlite3.connect('tickets.db')
cursor = db.cursor()

# Funções auxiliares para desempenho
def tempo_decorrido(timestamp):
    now = datetime.now()
    delta = now - timestamp
    if delta.days > 0:
        return f"{delta.days} dias atrás"
    elif delta.seconds > 3600:
        return f"{delta.seconds // 3600} horas atrás"
    elif delta.seconds > 60:
        return f"{delta.seconds // 60} minutos atrás"
    else:
        return "menos de 1 minuto atrás"

def ultimo_ticket_fechado():
    cursor.execute('SELECT closed_at FROM tickets WHERE status = "closed" ORDER BY closed_at DESC LIMIT 1')
    result = cursor.fetchone()
    if result:
        return datetime.strptime(result[0], '%Y-%m-%d %H:%M:%S')
    return None

def ultima_mensagem():
    cursor.execute('SELECT timestamp FROM mensagens ORDER BY timestamp DESC LIMIT 1')
    result = cursor.fetchone()
    if result:
        return datetime.strptime(result[0], '%Y-%m-%d %H:%M:%S')
    return None


# Comando para ver o desempenho
@bot.tree.command(name="desempenho", description="Veja o desempenho individual de cada atendente.")
async def desempenho(interaction: discord.Interaction):
    user_id = interaction.user.id  # Obtém o ID do usuário que usou o comando

    db = sqlite3.connect('tickets.db')
    cursor = db.cursor()  
    # Número de tickets atendidos pelo usuário atual
    cursor.execute('SELECT COUNT(*) FROM tickets WHERE staff_id = ? AND status = "closed"', (user_id,))
    tickets_atendidos = cursor.fetchone()[0]

    # Total de mensagens registradas pelo usuário atual
    cursor.execute('SELECT COUNT(*) FROM mensagens WHERE user_id = ?', (user_id,))
    total_mensagens = cursor.fetchone()[0]

    # Mensagens trocadas no bate-papo (fora dos tickets) pelo usuário atual
    cursor.execute('SELECT COUNT(*) FROM mensagens WHERE user_id = ? AND user_id NOT IN (SELECT staff_id FROM tickets)', (user_id,))
    mensagens_bate_papo = cursor.fetchone()[0]

    # Obtendo os dados de tempo real
    cursor.execute('SELECT closed_at FROM tickets WHERE staff_id = ? AND status = "closed" ORDER BY closed_at DESC LIMIT 1', (user_id,))
    ultimo_ticket_result = cursor.fetchone()
    ultimo_ticket = datetime.strptime(ultimo_ticket_result[0], '%Y-%m-%d %H:%M:%S') if ultimo_ticket_result else None

    cursor.execute('SELECT timestamp FROM mensagens WHERE user_id = ? ORDER BY timestamp DESC LIMIT 1', (user_id,))
    ultima_msg_result = cursor.fetchone()
    ultima_msg = datetime.strptime(ultima_msg_result[0], '%Y-%m-%d %H:%M:%S') if ultima_msg_result else None

    # Calculando o tempo decorrido para o último ticket e a última mensagem
    tempo_ticket = tempo_decorrido(ultimo_ticket) if ultimo_ticket else "Nenhum ticket fechado"
    tempo_mensagem = tempo_decorrido(ultima_msg) if ultima_msg else "Nenhuma mensagem registrada"


    # Criando o embed com informações individuais
    embed = discord.Embed(
        title="Seu Relatório de Desempenho:",
        description=f"Usuário: {interaction.user.mention}",
        color=discord.Color.yellow(),
        timestamp=interaction.created_at
    )

    embed.add_field(name="📩 Tickets atendidos:", value=f"**{tickets_atendidos}**")
    embed.add_field(name="📋 Total de mensagens:", value=f"**{total_mensagens}**")
    embed.add_field(name="💬 Mensagens no bate-papo:", value=f"**{mensagens_bate_papo}**")
    embed.add_field(name="🕒 Último ticket fechado:", value=f"**{tempo_ticket}**")
    embed.add_field(name="🕓 Última mensagem registrada:", value=f"**{tempo_mensagem}**")
    embed.set_footer(text="*Desenvolvedores: TrovãoAzul e Aki")

    await interaction.response.send_message(embed=embed)

id_cargo_atendente = 1310322685468868690 # ID do cargo de atendente
log_channel_id = 1310323047563132960  # ID do canal de log

@bot.event
async def on_message(message):
    if not message.author.bot:
        await registrar_mensagem(message.author.id)
    await bot.process_commands(message)


async def registrar_mensagem(user_id):
    timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    db = sqlite3.connect('tickets.db')
    cursor = db.cursor()  
    cursor.execute("INSERT INTO mensagens (user_id, timestamp) VALUES (?, ?)", (user_id, timestamp))
    db.commit()
    db = sqlite3.connect('tickets.db')
    cursor = db.cursor()  

# IDs dos cargos (você precisa fornecer estes IDs)
cargo_ids = {
    "Dono": 123456789012345678,
    "Sub-Dono": 1240283766589493317,
    "Fundador": 234567890123456789,
    "Cofundador": 1257792320388989079,
    "Ceo": 1240283766606401607,
    "Presidente": 1240283766606401606,
    "Vice-presidente": 1240283766589493318,
    "Gestor": 1240283766589493316,
    "Designer gráfico": 1240283766589493315,
    "Diretor": 1240283766589493314,
    "Gerência": 1240283766589493313,
    "Coordenador": 1240283766577037451,
    "Mentor": 1240283766577037450,
    "Moderador Líder": 1240283766577037449,
    "Moderador Novato": 1240283766577037448,
    "Suporte": 1240283766577037447,
    "Aprendiz": 1310322595597652041,
} 



async def create_mural_embed(guild):
    embed = discord.Embed(title="══════════⊹⊱≼𝗠𝗨𝗥𝗔𝗟 𝗦𝗧𝗔𝗙𝗙≽⊰⊹══════════", color=0xFC9EFF)
    
    descricao = ""
    
    for cargo_nome, cargo_id in cargo_ids.items():
        cargo = guild.get_role(cargo_id)
        if not cargo:
            continue
        
        membros = [m.mention for m in cargo.members]
        if membros:
            descricao += f"**Atualmente no cargo de** <@&{cargo_id}>:\n{',╺╸'.join(membros)}\n\n"
        else:
            descricao += f"**Atualmente no cargo de** <@&{cargo_id}>:\nNão há ninguém com esse cargo\n\n"
    embed.set_image(url="https://www.imagensanimadas.com/data/media/562/linha-imagem-animada-0184.gif")
    embed.description = descricao
    return embed

class MuralView(View):
    def __init__(self, guild):
        super().__init__(timeout=None)
        self.guild = guild

    @discord.ui.button(label="Atualizar", style=discord.ButtonStyle.grey, emoji="<a:red_brilho:806565883346550905>")
    async def update_mural(self, interaction: discord.Interaction, button: Button):
        embed = await create_mural_embed(self.guild)
        await interaction.response.edit_message(embed=embed, view=self)

@bot.command()
async def mural(ctx):
    embed = await create_mural_embed(ctx.guild)
    view = MuralView(ctx.guild)
    await ctx.send(embed=embed, view=view)

# Variável global para armazenar a mensagem da denúncia
denuncia_mensagem = None

# Banco de dados SQLite
conn = sqlite3.connect('denuncias.db')
cursor = conn.cursor()
cursor.execute('''
    CREATE TABLE IF NOT EXISTS denuncias (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        contador INTEGER DEFAULT 0,
        ultima_reset TEXT
    )
''')
conn.commit()

# Função para gerenciar a contagem semanal
def atualizar_contador(user_id: int) -> int:
    """Atualiza o contador semanal de denúncias do usuário."""
    tz = pytz.timezone('America/Sao_Paulo')
    hoje = datetime.datetime.now(tz).date()
    db = sqlite3.connect('denuncias.db')
    cursor = db.cursor()
    cursor.execute('SELECT contador, ultima_reset FROM denuncias WHERE user_id = ?', (user_id,))
    resultado = cursor.fetchone()

    if resultado:
        contador, ultima_reset = resultado
        ultima_reset = datetime.date.fromisoformat(ultima_reset)
        if hoje.weekday() == 0 and hoje != ultima_reset:
            # Segunda-feira: reiniciar contador
            db = sqlite3.connect('denuncias.db')
            cursor = db.cursor()
            contador = 1
            cursor.execute('UPDATE denuncias SET contador = ?, ultima_reset = ? WHERE user_id = ?', (contador, hoje.isoformat(), user_id))
        else:
            db = sqlite3.connect('denuncias.db')
            cursor = db.cursor()
            # Incrementar contador
            contador += 1
            cursor.execute('UPDATE denuncias SET contador = ? WHERE user_id = ?', (contador, user_id))
    else:
        # Novo usuário no sistema
        db = sqlite3.connect('denuncias.db')
        cursor = db.cursor()
        contador = 1
        cursor.execute('INSERT INTO denuncias (user_id, contador, ultima_reset) VALUES (?, ?, ?)', (user_id, contador, hoje.isoformat()))

    conn.commit()
    return contador


# Dropdown para escolher regras quebradas
class RegrasDropdown(discord.ui.Select):
    def __init__(self, denunciante: discord.Member, denunciado: discord.Member, explicacao: str, provas: discord.Attachment):
        self.denunciante = denunciante
        self.denunciado = denunciado
        self.explicacao = explicacao
        self.provas = provas

        options = [
            discord.SelectOption(label="Spam", description="Envio excessivo de mensagens"),
            discord.SelectOption(label="Ofensa", description="Ofensa direta a membros"),
            discord.SelectOption(label="Conteúdo impróprio", description="Envio de conteúdo inadequado"),
            discord.SelectOption(label="Flood", description="Mensagens repetidas rapidamente"),
            discord.SelectOption(label="Outro", description="Outra regra quebrada")
        ]
        super().__init__(placeholder="Escolha a regra quebrada...", options=options)
    
    async def callback(self, interaction: discord.Interaction):
        global denuncia_mensagem
        regra = self.values[0]

        canal = interaction.guild.get_channel(CANAL_DENUNCIAS_ID)
        if not canal:
            await interaction.response.send_message("❌ O canal de denúncias não foi encontrado.", ephemeral=True)
            return

        # Atualizar contador semanal
        numero_denuncia = atualizar_contador(self.denunciante.id)

        embed = discord.Embed(
            title="📢 Nova Denúncia Recebida",
            description=(
                f"**Regra quebrada:** {regra}\n"
                f"**Denunciante:** {self.denunciante.mention}\n"
                f"**Denunciado:** {self.denunciado.mention}\n\n"
                f"📊 Essa é a denúncia número **{numero_denuncia}** feita pelo helper **{self.denunciante.name}** nesta semana."
            ),
            color=discord.Color.dark_theme()
        )
        embed.add_field(name="Status", value="🕒 Em Análise", inline=False)
        
        if self.explicacao:
            embed.add_field(name="Explicação:", value=self.explicacao, inline=False)
        
        if self.provas:
            embed.set_image(url=self.provas.url)

        mensagem = await canal.send(embed=embed, view=DenunciaRespostaView(self.denunciante, self.denunciado))
        denuncia_mensagem = mensagem

        await interaction.response.send_message("✅ Sua denúncia foi enviada com sucesso!", ephemeral=True)


# Comando de denúncia
@bot.tree.command(name="denuncia", description="Envie uma denúncia com provas.")
@app_commands.describe(
    denunciado="Mencione o usuário que está sendo denunciado.",
    explicacao="Descreva a situação (opcional)",
    provas="Anexe uma imagem, vídeo ou áudio como prova"
)
async def denuncia(interaction: discord.Interaction, denunciado: discord.Member, explicacao: str = None, provas: discord.Attachment = None):
    await interaction.response.send_message(
        "Escolha a regra quebrada na lista abaixo:",
        view=discord.ui.View().add_item(RegrasDropdown(interaction.user, denunciado, explicacao, provas)),
        ephemeral=True
    )


# View para staff aceitar ou negar denúncia
class DenunciaRespostaView(discord.ui.View):
    def __init__(self, denunciante: discord.Member, denunciado: discord.Member):
        super().__init__(timeout=None)
        self.denunciante = denunciante
        self.denunciado = denunciado

    @discord.ui.button(label="Aceitar Denúncia", style=discord.ButtonStyle.green)
    async def aceitar(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("✅ Denúncia aceita e processada.", ephemeral=True)

    @discord.ui.button(label="Negar Denúncia", style=discord.ButtonStyle.red)
    async def negar(self, interaction: discord.Interaction, button: discord.ui.Button):
        global denuncia_mensagem
        if not denuncia_mensagem:
            await interaction.response.send_message("❌ A mensagem de denúncia não pôde ser encontrada.", ephemeral=True)
            return

        embed = denuncia_mensagem.embeds[0]
        embed.color = discord.Color.red()
        embed.set_field_at(1, name="Status", value="❌ Negada")

        await denuncia_mensagem.edit(embed=embed, view=None)
        await interaction.response.send_message("🚫 Denúncia negada com sucesso.", ephemeral=True)

# Conexão com o banco de dados SQLite
conn = sqlite3.connect('vips.db')
cursor = conn.cursor()

# Criação da tabela se não existir
cursor.execute('''
CREATE TABLE IF NOT EXISTS vips (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    setter_id INTEGER,
    target_id INTEGER,
    vip_type TEXT
)
''')
conn.commit()

# Dropdown para seleção de VIPs
class Dropdown2(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(value="Vip1", label="Vip 1"),
            discord.SelectOption(value="Vip2", label="Vip 2"),
        ]
        super().__init__(
            placeholder="Selecione o vip...",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="dropdown2"
        )

    async def callback(self, interaction: discord.Interaction):
        selected_value = self.values[0]

        if selected_value == "Vip1":
            cargo_id = 1321813494097510511
            cargo = interaction.guild.get_role(cargo_id)
            await user2.add_roles(cargo)
            vip_type = "Vip1"
        elif selected_value == "Vip2":
            cargo_id = 1321813533696065609
            cargo = interaction.guild.get_role(cargo_id)
            await user2.add_roles(cargo)
            vip_type = "Vip2"
        
        # Salvar no banco de dados
        cursor.execute('INSERT INTO vips (setter_id, target_id, vip_type) VALUES (?, ?, ?)', 
                       (interaction.user.id, user2.id, vip_type))
        conn.commit()

        await interaction.response.send_message(f"{vip_type} foi setado no usuário {user2.mention}!", ephemeral=True)

user2 = None

class DropdownView2(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(Dropdown2())

# Comando para definir VIP
@bot.tree.command(name="setvip", description="Set vip em um usuário.")
@commands.has_permissions(kick_members=True)
@app_commands.describe(
    usuario="O usuário que você deseja setar o vip"
)
async def setvip(interaction: discord.Interaction, usuario: discord.User):
    global user2
    user2 = usuario
    embed = discord.Embed(title="Vips:", description="Escolha qual VIP deseja setar abaixo;", color=0x000000)
    embed.set_thumbnail(url="https://www.tibiawiki.com.br/images/c/c3/Tibiapedia.gif")
    embed.set_image(url="https://www.imagensanimadas.com/data/media/562/linha-imagem-animada-0446.gif")
    view = DropdownView2()
    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

# Comando para verificar VIPs
@bot.tree.command(name="statusvips", description="Veja os VIPs que um usuário setou.")
@app_commands.describe(
    usuario="O usuário que você deseja verificar"
)
async def statusvips(interaction: discord.Interaction, usuario: discord.User):
    cursor.execute('SELECT vip_type, target_id FROM vips WHERE setter_id = ?', (usuario.id,))
    registros = cursor.fetchall()
    
    if not registros:
        await interaction.response.send_message(f"{usuario.mention} não setou nenhum VIP.", ephemeral=True)
        return
    
    embed = discord.Embed(title=f"VIPs setados por {usuario.name}", color=0xFFD700)
    for vip_type, target_id in registros:
        target_user = interaction.guild.get_member(target_id)
        target_name = target_user.name if target_user else "Usuário desconhecido"
        embed.add_field(name=vip_type, value=f"Setado em: {target_name}", inline=False)
    
    await interaction.response.send_message(embed=embed, ephemeral=True)


CANAL_DENUNCIAS_ID = 1310323047563132960  # Canal onde as denúncias serão enviadas
GUILD_ID = 1308793404385398784  # ID do servidor

DATABASE_PATH = os.path.join(os.path.dirname(__file__), 'srdark_coins.db')

# Conectar ao banco de dados e criar a tabela se não existir
def initialize_db():
    with sqlite3.connect(DATABASE_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS economy (
            user_id INTEGER PRIMARY KEY,
            balance INTEGER DEFAULT 0,
            last_daily INTEGER DEFAULT 0
        )
        ''')
        conn.commit()

initialize_db()

# Função para obter o saldo de um usuário
def get_balance(user_id):
    with sqlite3.connect(DATABASE_PATH) as conn:
        c = conn.cursor()
        c.execute('SELECT balance FROM economy WHERE user_id = ?', (user_id,))
        result = c.fetchone()
        if result is None:
            c.execute('INSERT INTO economy (user_id, balance) VALUES (?, ?)', (user_id, 0))
            conn.commit()
            return 0
        return result[0]

# Função para atualizar o saldo de um usuário
def update_balance(user_id, amount):
    with sqlite3.connect(DATABASE_PATH) as conn:
        c = conn.cursor()
        c.execute('UPDATE economy SET balance = balance + ? WHERE user_id = ?', (amount, user_id))
        conn.commit()

# Função para obter o último uso do comando daily
def get_last_daily(user_id):
    with sqlite3.connect(DATABASE_PATH) as conn:
        c = conn.cursor()
        c.execute('SELECT last_daily FROM economy WHERE user_id = ?', (user_id,))
        result = c.fetchone()
        if result is None:
            c.execute('INSERT INTO economy (user_id, last_daily) VALUES (?, ?)', (user_id, 0))
            conn.commit()
            return 0
        return result[0]

# Função para atualizar o último uso do comando daily
def update_last_daily(user_id, timestamp):
    with sqlite3.connect(DATABASE_PATH) as conn:
        c = conn.cursor()
        c.execute('UPDATE economy SET last_daily = ? WHERE user_id = ?', (timestamp, user_id))
        conn.commit()

# Função para converter valores abreviados
def parse_amount(amount_str):
    match = re.match(r"(\d+)([kKmM]?)", amount_str)
    if match:
        number = int(match.group(1))
        suffix = match.group(2).lower()
        if suffix == 'k':
            return number * 1000
        elif suffix == 'm':
            return number * 1000000
        else:
            return number
    else:
        raise ValueError("Invalid amount format")

@bot.command(name='bal')
async def bal(ctx, member: discord.Member = None):
    if member is None:
        member = ctx.author
    
    user_id = member.id
    balance = get_balance(user_id)
    
    if member == ctx.author:
        await ctx.send(f'{member.mention}, você tem **<:srdarkcoins:1328477435200667648> {balance} Srdark Coins.**')
    else:
        await ctx.send(f'{ctx.author.mention}, {member.mention} tem **<:srdarkcoins:1328477435200667648>{balance} Srdark Coins.**')

@bot.command(name='daily')
async def daily(ctx):
    user_id = ctx.author.id
    current_time = int(time.time())
    last_daily = get_last_daily(user_id)
    
    if current_time - last_daily < 86400:  # 86400 segundos = 24 horas
        time_left = 86400 - (current_time - last_daily)
        next_claim_time = current_time + time_left
        await ctx.send(f'{ctx.author.mention},\n<:srdarkcoins:1328477435200667648> **|** Você já recebeu sua Recompensa Diariamente!\n\n'
                       f'<:checkroxo:1328485567591354509> **|** Atenção: Lembrando que você pode pegar a recompensa diária todos os dias e, você pode pegar novamente em <t:{next_claim_time}:t>!')
        return
    
    amount = random.randint(2000, 5000)
    update_balance(user_id, amount)
    update_last_daily(user_id, current_time)
    balance = get_balance(user_id)
    next_claim_time = current_time + 86400
    await ctx.send(f'{ctx.author.mention},\n<:srdarkcoins:1328477435200667648> **|** Receba a sua Recompensa Diariamente!\n\n'
                   f'<:slayer_SantaGiftBox:1328485722109382779> **|** Quantia: {amount}SrdarkCoins\n\n'
                   f'<:checkroxo:1328485567591354509> **|** Atenção: Lembrando que você pode pegar a recompensa diária todos os dias e, se você pegar agora, você poderá pegar a recompensa diária novamente em <t:{next_claim_time}:t>!')

@bot.command(name='pay')
async def pay(ctx, member: discord.Member, amount: str):
    sender_id = ctx.author.id
    receiver_id = member.id
    amount = parse_amount(amount)
    
    if amount <= 0:
        await ctx.send(f'{ctx.author.mention}, o valor deve ser positivo.')
        return
    
    sender_balance = get_balance(sender_id)
    if sender_balance < amount:
        await ctx.send(f'{ctx.author.mention}, você não tem Srdark Coins suficientes para transferir.')
        return
    
    update_balance(sender_id, str(-amount))
    update_balance(receiver_id, str(amount))
    await ctx.send(f'{ctx.author.mention} transferiu **<:srdarkcoins:1328477435200667648> {amount} Srdark Coins** para {member.mention}.')

products = [
    {"name": "VIP Dragon", "price": 20000, "description": "Acesso VIP Dragon", "role_id": 1258479012028747828},
    {"name": "VIP Eclipse", "price": 30000, "description": "Acesso VIP Eclipse", "role_id": 1258479013047963760},
    {"name": "VIP Soul", "price": 45000, "description": "Acesso VIP Soul", "role_id": 1258479013941215365},
    {"name": "VIP UwU", "price": 65000, "description": "Acesso VIP UwU", "role_id": 1258201893910351994},
    {"name": "VIP Phoenix", "price": 100000, "description": "Acesso VIP Phoenix", "role_id": 1258479027631423570},
    {"name": "VIP Essence", "price": 150000, "description": "Acesso VIP Essence", "role_id": 1258479028197789736},
    {"name": "VIP Void", "price": 235000, "description": "Acesso VIP Void", "role_id": 1258479046564778124},
    {"name": "VIP Killer", "price": 340000, "description": "Acesso VIP Killer", "role_id": 1258479047214895234},
    {"name": "VIP Gold", "price": 500000, "description": "Acesso VIP Gold", "role_id": 1258479047873269860},
    {"name": "VIP Thunder", "price": 700000, "description": "Acesso VIP Thunder", "role_id": 1258479061953417216},
    {"name": "VIP Infinity", "price": 1000000, "description": "Acesso VIP Infinity", "role_id": 1258479062142156901},
    {"name": "VIP Soul Reaper", "price": 1400000, "description": "Acesso VIP Soul Reaper", "role_id": 1258596475101773824},
    {"name": "VIP Nightmer", "price": 2000000, "description": "Acesso VIP Nightmer", "role_id": 1258596475286323295},
    {"name": "VIP Shenanigans", "price": 2750000, "description": "Acesso VIP Shenanigans", "role_id": 1258604775591907390},
    {"name": "VIP Cookie", "price": 3500000, "description": "Acesso VIP Cookie", "role_id": 1258596476762853418},
    {"name": "VIP Blizzard", "price": 5000000, "description": "Acesso VIP Blizzard", "role_id": 1258596477144535040},
    {"name": "VIP Blood", "price": 7000000, "description": "Acesso VIP Blood", "role_id": 1258604776539820075},
    {"name": "VIP Z҉̡̏͝a̶͢͡l̵҇͜g҉̢͗͠o̴̡͡", "price": 1000000, "description": "Acesso VIP Z҉̡̏͝a̶͢͡l̵҇͜g҉̢͗͠o̴̡͡", "role_id": 1258814259882885282},
    {"name": "VIP ¿Mystery?", "price": 15000000, "description": "Acesso VIP ¿Mystery?", "role_id": 1258615948173119548},
    {"name": "VIP Minøs Øne", "price": 20000000, "description": "Acesso VIP Minøs Øne", "role_id": 1258820781056593990},
]

# Verifica se o usuário possui o cargo para desconto
DISCOUNT_ROLE_ID = 1257071596313776198

class StoreView(View):
    def __init__(self, user_id, page=0):
        super().__init__(timeout=None)
        self.user_id = user_id
        self.page = page
        self.max_page = (len(products) - 1) // 1  # Cada página mostra 1 produto

        # Botões de navegação
        self.previous_button = Button(label='Anterior', style=discord.ButtonStyle.secondary, custom_id=f'previous_{user_id}')
        self.previous_button.callback = self.previous_page
        self.add_item(self.previous_button)

        self.page_label = Button(label=f'Página {self.page + 1}/{self.max_page + 1}', style=discord.ButtonStyle.secondary, disabled=True)
        self.add_item(self.page_label)

        self.next_button = Button(label='Próximo', style=discord.ButtonStyle.secondary, custom_id=f'next_{user_id}')
        self.next_button.callback = self.next_page
        self.add_item(self.next_button)

        # Botão de compra
        for product in products[self.page:self.page + 1]:
            buy_button = Button(label=f'Comprar {product["name"]} - {product["price"]} Srdark Coins', style=discord.ButtonStyle.primary, custom_id=f'buy_{product["name"]}_{user_id}')
            buy_button.callback = self.buy_product
            self.add_item(buy_button)

    async def interaction_check(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Você não pode interagir com esta loja.", ephemeral=True)
            return False
        return True

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        await self.message.edit(view=self)

    async def previous_page(self, interaction: discord.Interaction):
        if self.page > 0:
            self.page -= 1
            await self.update_store(interaction)
        else:
            await interaction.response.send_message("Você já está na primeira página.", ephemeral=True)

    async def next_page(self, interaction: discord.Interaction):
        if self.page < self.max_page:
            self.page += 1
            await self.update_store(interaction)
        else:
            await interaction.response.send_message("Você já está na última página.", ephemeral=True)

    async def buy_product(self, interaction: discord.Interaction):
        button = interaction.data['custom_id']
        product_name = button.split('_')[1]
        product = next(p for p in products if p["name"] == product_name)
        balance = get_balance(self.user_id)
        
        # Verifica se o usuário tem o cargo de desconto
        has_discount_role = interaction.user.get_role(DISCOUNT_ROLE_ID) is not None
        discount_price = product["price"] * 0.6 if has_discount_role else product["price"]

        if balance < discount_price:
            await interaction.response.send_message(f"Você não tem Srdark Coins suficientes para comprar {product_name}.", ephemeral=True)
        else:
            update_balance(self.user_id, f'-{discount_price}')
            role = interaction.guild.get_role(product["role_id"])
            await interaction.user.add_roles(role)
            await interaction.response.send_message(f"Você comprou {product_name} por <:srdarkcoins:1328477435200667648>{discount_price} Srdark Coins e recebeu o cargo correspondente.")

    async def update_store(self, interaction: discord.Interaction):
        for item in self.children[:]:
            self.remove_item(item)
        
        # Botões de navegação
        self.add_item(self.previous_button)
        self.page_label.label = f'Página {self.page + 1}/{self.max_page + 1}'
        self.add_item(self.page_label)
        self.add_item(self.next_button)

        # Botão de compra
        for product in products[self.page:self.page + 1]:
            buy_button = Button(label=f'Comprar {product["name"]} - {product["price"]} Srdark Coins', style=discord.ButtonStyle.primary, custom_id=f'buy_{product["name"]}_{self.user_id}')
            buy_button.callback = self.buy_product
            self.add_item(buy_button)

        # Atualizar o embed
        product = products[self.page]
        embed = discord.Embed(
            title="__Loja VIP__",
            description=f"**{product['name']}\n\n{product['description']}\n\nPreço: {product['price']} moedas**",
            color=discord.Color.from_rgb(0, 0, 0)
        )
        embed.set_thumbnail(url="https://www.tibiawiki.com.br/images/c/c3/Tibiapedia.gif")
        embed.set_image(url="https://linktr.ee/og/image/srdarkdiscord.jpg")
        embed.set_author(name='Sr.Dark', icon_url='https://www.tibiawiki.com.br/images/3/31/Scroll_of_the_Stolen_Moment.gif')

        await interaction.response.edit_message(embed=embed, view=self)

@bot.tree.command(name='store')
async def store(interaction: discord.Interaction):
    embed = discord.Embed(
        title="__Loja VIP__",
        description=f"**{products[0]['name']}\n\n{products[0]['description']}\n\nPreço: {products[0]['price']} moedas**",
        color=discord.Color.from_rgb(0, 0, 0)
    )
    embed.set_thumbnail(url="https://www.tibiawiki.com.br/images/c/c3/Tibiapedia.gif")
    embed.set_image(url="https://linktr.ee/og/image/srdarkdiscord.jpg")
    embed.set_author(name='Sr.Dark', icon_url='https://www.tibiawiki.com.br/images/3/31/Scroll_of_the_Stolen_Moment.gif')

    view = StoreView(interaction.user.id)
    message = await interaction.response.send_message(embed=embed, view=view)
    view.message = message


# Comando para adicionar dinheiro a um usuário
@bot.tree.command(name='add_money', description="Adiciona dinheiro a um usuário. Apenas administradores podem usar este comando.")
@app_commands.describe(member="O membro para quem você quer adicionar dinheiro.", amount="A quantidade de dinheiro para adicionar.")
@app_commands.checks.has_permissions(administrator=True)
async def add_money(interaction: discord.Interaction, member: discord.Member, amount: str):
    try:
        parsed_amount = parse_amount(str(amount))
        if parsed_amount <= 0:
            await interaction.response.send_message("A quantidade deve ser maior que zero.", ephemeral=True)
            return

        update_balance(member.id, parsed_amount)
        await interaction.response.send_message(f"Adicionados {amount} moedas para {member.mention}.", ephemeral=True)
    except ValueError:
        await interaction.response.send_message("Formato de quantidade inválido. Use números com k para mil ou m para milhão, por exemplo, 2k ou 1m.", ephemeral=True)

@bot.event
async def on_ready():
    print("Estou conectado!!!")
    try:
        synced = await bot.tree.sync()
        print(f"Sincronizado {len(synced)} comando(s)")
    except Exception as e:
        print(f"Ocorreu um erro: {e}")

bot.run('')