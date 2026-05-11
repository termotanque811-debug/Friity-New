import os
import re
import uuid
import json
import random
import asyncio
import pathlib
import threading
import discord
import aiohttp
from groq import AsyncGroq
from datetime import datetime, timezone
from collections import defaultdict

DISCORD_BOT_TOKEN = os.environ["DISCORD_BOT_TOKEN"]
GROQ_API_KEY = os.environ["GROQ_API_KEY"]

groq_client = AsyncGroq(api_key=GROQ_API_KEY)

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

client = discord.Client(intents=intents)

TRYOUTER_ROLE_ID = 1447060651003346995
POLL_ROLE_ID = 1490466480318582804
POLL_PING_ROLE_ID = 1490463201450655835
POLL_CHANNEL_ID = 1490463944245117108
POLL_NOTIFICATION_CHANNEL_ID = 1490463201450655835

_POLL_ACCENT_COLORS = [0x5865F2, 0x57F287, 0xED4245, 0x9B59B6, 0xE67E22]

DISCORD_API_BASE = "https://discord.com/api/v10"
COMPONENTS_V2_FLAG = 32768
GUILD_ID = 1447027458845970656

active_polls: dict[str, "PollState"] = {}
active_activity_checks: dict[str, "ActivityCheckState"] = {}
ACTIVITY_EXCLUDED_IDS: set[int] = {1162798183068467220, 1025178585104920656}
STREAKS_FILE = pathlib.Path("streaks.json")
ACTIVITY_STATE_FILE = pathlib.Path("activity_state.json")
USER_REGISTRY_FILE = pathlib.Path("user_registry.json")

# Registro in-memory de usuarios por guild. Se persiste a USER_REGISTRY_FILE.
# Estructura: { guild_id_str: { "name": str, "updated_at": iso, "users": { user_id_str: {..entry..} } } }
_user_registry: dict[str, dict] = {}
_registry_dirty_count: int = 0
_REGISTRY_SAVE_EVERY: int = 10  # guardar a disco cada N updates para no martillar el FS
_STREAK_ROLE_NAME_RE = re.compile(r"^Streak (\d+)$")
current_check_id: str | None = None
streak_lock = asyncio.Lock()

RULES_IMAGE_URL = (
    "https://cdn.discordapp.com/attachments/1480321316996517930/1487859222979940582/"
    "Screenshot_20250329_140042_ChatGPT.jpg?ex=69caac61&is=69c95ae1"
    "&hm=1ad17b569ef17b4051da4c595192ab13336e115e7fd1e432ce7d3982dbece29a&"
)

RULES_GIF_URL = "https://cdn.discordapp.com/attachments/1451654847408373947/1489652043986505979/20250403_124512.gif"

RULES_BOTTOM_IMAGE_URL = (
    "https://cdn.discordapp.com/attachments/1451654847408373947/1487884473184817152/"
    "2316529eeadd144bdc1cabb605b10420.jpg?ex=69cac3e5&is=69c97265"
    "&hm=732b940fa5455a5480f91ce4d9815f03614702c8df490290905b5eea3ceadf94&"
)

PUNISHMENTS_URL = "https://discord.com/channels/1447027458845970656/1487884455728124014"

RULES_DATA = {
    "en": {
        "rules": [
            ("Racism",         "Any form of racism (slurs, race, or religion) is strictly prohibited."),
            ("Common Sense",   "Be respectful. No offensive or Nazi jokes, or family-related insults."),
            ("NSFW",           "No +18 or adult content. Violation results in a permanent ban."),
            ("Advertising",    "No self-promotion or advertising other clans/servers."),
            ("Spam/Flood",     "No spamming (5-6 messages) or flooding (8+ lines)."),
            ("Sensitive Jokes","Jokes about assault or suicide will lead to a blacklist."),
        ],
        "sanctions": ("Sanctions", "1 Warn = 1h Mute | 2 Warns = 6h Mute | 3 Warns = Ban *(Appealable)*"),
    },
    "es": {
        "rules": [
            ("Racismo",         "Cualquier forma de racismo no sera tolerada (n-word, raza o religion)."),
            ("Sentido Comun",   "No digas cosas fuera de tema o chistes ofensivos."),
            ("NSFW",            "Prohibido contenido +18. Resultara en baneo inmediato."),
            ("Publicidad",      "Prohibido promocionar otros clanes o servidores."),
            ("Spam/Flood",      "No spamear (5-6 msgs seguidos) ni flood (mas de 8 lineas)."),
            ("Temas Sensibles", "Chistes de abuso o suicidio resultaran en baneo o blacklist."),
        ],
        "sanctions": ("Sanciones", "1 Warn = 1h Mute | 2 Warns = 6h Mute | 3 Warns = Ban *(Apelable)*"),
    },
    "pt": {
        "rules": [
            ("Racismo",          "Qualquer forma de racismo nao sera tolerada."),
            ("Bom senso",        "Use o bom senso. Sem piadas nazistas ou sobre a familia de outros."),
            ("NSFW",             "NAO envie conteudo +18. Isso resultara em banimento."),
            ("Autopromocao",     "Proibido divulgar outros servidores ou clas."),
            ("Spam",             "Proibido spam ou mensagens com mais de 8 linhas."),
            ("Piadas sensiveis", "Piadas sobre estupro ou suicidio resultarao em banimento."),
        ],
        "sanctions": ("Punicoes", "1 Warn = 1h Mute | 2 Warns = 6h Mute | 3 Warns = Ban *(Apelavel)*"),
    },
}


def build_rule_embeds(lang_key: str) -> list[discord.Embed]:
    data = RULES_DATA[lang_key]
    embeds = []
    for name, text in data["rules"]:
        embed = discord.Embed(
            title=f"➤ {name}",
            description=f"│ {text}",
            color=0xFF69B4,
        )
        embed.set_image(url=RULES_BOTTOM_IMAGE_URL)
        embeds.append(embed)
    sanction_name, sanction_text = data["sanctions"]
    sanctions_embed = discord.Embed(
        title=f"➤ {sanction_name}",
        description=f"│ {sanction_text}",
        color=0xFF69B4,
    )
    sanctions_embed.set_image(url=RULES_BOTTOM_IMAGE_URL)
    embeds.append(sanctions_embed)
    return embeds


ALL_TIER_ROLES = [
    1447047863736602777,
    1447049414051889234,
    1453228943283982469,
    1447050940187283648,
    1447049536781418619,
    1485358209760886894,
    1485358385389113476,
    1447056922158039062,
    1447056940856377434,
    1447056957868478554,
    1447056974934966353,
    1447056992358105190,
    1447057117533048985,
]

TIER_ROLES = {
    "0":        1447047863736602777,
    "1":        1447049414051889234,
    "app":      1453228943283982469,
    "aplicant": 1453228943283982469,
    "2":        1447050940187283648,
    "3":        1447049536781418619,
    "4":        1485358209760886894,
    "5":        1485358385389113476,
}

SUBTIER_ROLES = {
    "high": 1447056957868478554,
    "mid":  1447056940856377434,
    "low":  1447056922158039062,
}

CLASS_ROLES = {
    "strong": 1447057117533048985,
    "stable": 1447056992358105190,
    "weak":   1447056974934966353,
}

VALID_TIERS    = {"0", "1", "app", "aplicant", "2", "3", "4", "5"}
VALID_SUBTIERS = {"low", "mid", "high"}
VALID_CLASSES  = {"weak", "stable", "strong"}

TIER_COLORS = {
    "0":        0x000000,
    "1":        0x0055FF,
    "app":      0x0055FF,
    "aplicant": 0x0055FF,
    "2":        0x8000FF,
    "3":        0xFF1493,
    "4":        0xFF4500,
    "5":        0xFFD700,
}

conversation_history: dict[int, list[dict]] = defaultdict(list)

MAX_HISTORY_MESSAGES = 20

FALLBACK_MODELS = [
    "llama-3.3-70b-versatile",
    "meta-llama/llama-4-maverick-17b-128e-instruct",
    "meta-llama/llama-4-scout-17b-16e-instruct",
    "openai/gpt-oss-120b",
    "openai/gpt-oss-20b",
    "moonshotai/kimi-k2-instruct-0905",
    "qwen/qwen3-32b",
    "deepseek-r1-distill-llama-70b",
    "llama-3.1-8b-instant",
    "gemma2-9b-it",
]

_ASK_MAX_CYCLES = 3
_ASK_MODEL_429_DELAY = 1
_ASK_CYCLE_DELAY = 6

roblox_links: dict[int, str] = {}

BOT_OWNER_ID: int | None = None

SYSTEM_PROMPT = (
    "Eres Friity, el bot oficial del servidor de Discord del clan Celestials Dragons. "
    "Fuiste creado por Sid (también conocido como ffrsid). "
    "Tenés personalidad amigable y natural, como un humano real. "
    "Sabés todo sobre el clan Celestials Dragons, su servidor, y el competitivo de TSBL. "
    "Nunca inventás información que no tenés. Siempre respondés en el idioma del usuario (español, portugués o inglés).\n\n"

    "IDENTIDAD DEL SERVIDOR:\n"
    "- Vivís en el servidor de Discord de Celestials Dragons. Cuando alguien pregunta por 'el servidor' o 'el clan', se refieren a Celestials Dragons.\n"
    "- Hablás sobre Celestials Dragons cuando te preguntan sobre el servidor, sus miembros, roles o canales.\n"
    "- Solo mencionás TSBL cuando te preguntan explícitamente sobre reglas competitivas, phases, tiers o info de TSBL.\n"
    "- NUNCA digas 'no tengo acceso al servidor de TSBL'. Si alguien pregunta algo del servidor, decí 'Puedo revisar el servidor de Celestials Dragons para eso.'\n"
    "- Tu creador es Sid (ffrsid). Si alguien pregunta quién te hizo, decí que fue Sid.\n\n"

    "CANALES DEL SERVIDOR (Celestials Dragons):\n"
    "Nombre completo del server: \"死 Celestial Dragons | W.I.P\".\n"
    "\n"
    "Categoria \"☆一一Server-Stats一一☆\" (id 1451974164398342338):\n"
    "- Son 4 canales de voz (privados, solo vista) con estadisticas en vivo, puestas por el bot \"Server Stats\" (setup con /setup).\n"
    "- Muestran en el nombre del canal: All Members (total), Members (humanos), Bots, Boost (nivel de boost del server).\n"
    "- IMPORTANTE: NUNCA inventes ni repitas numeros hardcodeados para estas stats. El numero REAL y ACTUAL de miembros\n"
    "  SIEMPRE viene del bloque '[LIVE DATA - Server summary]' o '[LIVE DATA - Guild members]' que te pasa el sistema\n"
    "  en cada pregunta. Si te preguntan 'cuantos miembros hay', usa ESE numero, no uno memorizado.\n"
    "\n"
    "Categoria \"Welcome\":\n"
    "- #welcome (id 1451735485960552448): bienvenidas automaticas con el bot Sapphyre.\n"
    "  Mensaje: \"Welcome ${usermention} to **死 Celestial Dragons | W.I.P**! Pls Verify-here :)\".\n"
    "  Ademas manda un Dynamic Image: cuadro gris, avatar del user circular al centro, arriba \"Member #${guildmembercount}\", "
    "abajo \"Welcome ${userglobalnickname} to ${guildname}\", borde rosado arriba-izquierda y blanco abajo-derecha.\n"
    "- #exit (id 1447068049613127751): aviso cuando alguien sale del server. Formato unico: \"Bay User ${usermention}\".\n"
    "- #invite-tracker (id 1468772243160170536): cuenta las invitaciones al server por cada miembro. "
    "Objetivo: llegar a 10 invites para recibir un reward especial (todavia no definido el reward exacto).\n"
    "\n"
    "Instrucciones para usar estos datos:\n"
    "- Si te preguntan que hace cada canal o donde encontrar algo, usa ESTA info (no inventes).\n"
    "- Si piden el link del canal, usa el formato https://discord.com/channels/1447027458845970656/<channel-id>.\n"
    "- Si preguntan por un canal que no esta en esta lista, fijate en [LIVE DATA - Server channels] o deci que no lo tenes cargado todavia.\n\n"

    "PERSONALIDAD:\n"
    "- Respondé siempre de forma amigable, natural y útil. Nunca seas grosero ni agresivo.\n"
    "- Sonás como una persona real, no un robot. Usá vocabulario variado, nunca repitas las mismas frases.\n"
    "- Detectá el idioma del usuario y respondé siempre en ese idioma: español → español, portugués → portugués, inglés → inglés.\n\n"

    "HONESTIDAD Y DATOS EN TIEMPO REAL:\n"
    "- Si no sabés algo o no estás 100% seguro, decilo de forma clara y natural.\n"
    "- Usá formas variadas: 'Eso no lo tengo claro', 'La verdad no sé exactamente eso', 'No tengo esa info precisa', "
    "'Puedo revisar el servidor de Celestials Dragons para eso', 'No estoy seguro de eso, che', etc.\n"
    "- Nunca inventes información. Si no tenés los datos, decilo honestamente.\n"
    "- Cuando el sistema te proporciona secciones '[LIVE DATA — ...]', esos datos vienen directamente de la API de Discord y son 100% exactos. "
    "Usá esos números y nombres TAL CUAL aparecen. NUNCA inventes ni modifiques cantidades o nombres de miembros. "
    "Si la lista dice 3 miembros, son 3. Si dice 0, son 0. No redondees ni estimes.\n\n"

    "CORRECCIONES:\n"
    "- Si el usuario te corrige con frases como 'te equivocaste', 'eso está mal', 'no es así', reconocé el error de forma natural.\n"
    "- Usá respuestas variadas: '¡Gracias por corregirme!', 'Anotado bro', 'Tenés razón, me equivoqué', 'Gracias, lo corrijo', etc.\n"
    "- Recordá la corrección para el resto de la conversación.\n\n"

    "MEMORIA:\n"
    "- Tenés acceso al historial de la conversación actual con este usuario.\n"
    "- Si el usuario repite una pregunta, notalo y respondé de forma diferente o más completa.\n\n"

    "REGLAS DEL SERVIDOR:\n"
    "1. Respeto: No se tolera toxicidad. Bromas permitidas si no incomodan a nadie.\n"
    "2. Amenazas y violencia: Prohibidas de cualquier tipo.\n"
    "3. Discriminación: Prohibida. La N-word está completamente prohibida.\n"
    "4. Privacidad: No compartir info personal sin consentimiento.\n"
    "5. Difamación: No inventar info falsa sobre miembros. No aplica a temas competitivos.\n"
    "6. Contenido sexual: Prohibido. Tolerancia cero con menores.\n"
    "7. Links maliciosos: Prohibido malware, hacks, phishing.\n"
    "8. Spam y publicidad: No permitido sin aprobación del staff.\n\n"

    "SANCIONES:\n"
    "- 3 warns = blacklist temporal de 1 mes. Los warns duran 1 mes.\n"
    "- Blacklist: 1ra vez = 1 mes, aumenta hasta permanente.\n"
    "- Faltas graves = sanción inmediata: leaks, doxxeo, grooming, amenazas, acoso.\n"
    "- Líderes de clanes: 3 warns = no pueden registrar clanes. No afecta su participación como jugadores.\n"
    "- Blacklist de clanes: se publica públicamente con motivo, moderador, deadline y pruebas.\n\n"

    "TICKETS (Open-Ticket):\n"
    "- Registra Tu Clan: para participar en Glads.\n"
    "- Soporte De Staff / Ayuda: preguntas y problemas generales.\n"
    "- Duelos / Tops 1v1: desafiar a otros jugadores por su top.\n"
    "- Glads / Clan 5v5: desafiar a otros clanes por su posición.\n"
    "- Verify Issues: problemas con la verificación.\n"
    "- También existe el sistema de 1v1 Challenge para desafiar jugadores del leaderboard.\n\n"

    "PHASES (Sistema de clasificación):\n"
    "- Phase 0: Nivel Supremo. Dominio total, máximo nivel de LATAM.\n"
    "- Phase 1: Nivel Avanzado. Skill alta y estable, Top LATAM/SA.\n"
    "- Phase 2: Nivel Promedio. Consistentes, manejan lo esencial.\n"
    "- Phase 3: Nivel en Crecimiento. Fundamentos claros pero irregulares.\n"
    "- Phase 4: Principiante con Base. Entienden lo básico.\n"
    "- Phase 5: Nuevo en TSBL. Recién comienzan.\n\n"

    "TIERS dentro de cada Phase:\n"
    "- HIGH: Parte alta, casi listo para subir.\n"
    "- MID: Posición media y estable.\n"
    "- LOW: Zona baja, en desarrollo.\n\n"

    "SUB-TIERS:\n"
    "- STRONG: Dominio firme, cercano a ascenso.\n"
    "- STABLE: Rendimiento constante.\n"
    "- WEAK: En transición, trabajando para mejorar.\n\n"

    "HOSTS DISPONIBLES para obtener phase:\n"
    "- São Paulo, Brasil\n"
    "- Miami, Florida\n"
    "- Dallas, Texas (también para mexicanos)\n"
    "- Los Angeles, California (también para mexicanos)\n\n"

    "TRIALS / TRYOUTS:\n"
    "- Son sesiones donde un tryouter evalúa a jugadores para asignarles una phase.\n"
    "- Formato: FT3 o FT5 a elección del hoster.\n"
    "- Cuando dice LOCK: el server se cerró. Cuando dice ENDED: terminó la tryout.\n"
    "- La phase máxima que puede dar el tryouter es su propia phase, con tope en 2 High Strong.\n"
    "- Los resultados se registran con el comando >phase (en este server >tier).\n\n"

    "VOUCHS:\n"
    "- Sistema para recomendar jugadores para subir de phase.\n"
    "- Requisito mínimo: tener 1 Low Stable para poder vouchear.\n"
    "- Cada vouch necesita video completo sin cortes, phase actual y phase recomendada.\n"
    "- Los vouchs son validados por un Voucher Manager.\n\n"

    "COMPETITIVO - REGLAS:\n"
    "- Faltas prohibidas: Tab Glitch, Sneaking en 1v1/Glads, Passive Strike.\n"
    "- Techs prohibidas: Hunter's Grab abuse, Aba Macro, Sidedash Cancel Macro.\n"
    "- Techs permitidas: Lordheaven Combo, Double Ragdoll (con condiciones).\n"
    "- UNCAP de FPS permitido solo con Global Settings.\n"
    "- Jugadores con más de 190ms no pueden participar en Glads.\n"
    "- Glads sin CD están eliminadas y deben registrarse con referees.\n"
    "- Solo 2 norteamericanos por clan en Glads.\n"
    "- Mexicanos pueden jugar FT5 en Dallas y Miami.\n\n"

    "TECHS Y REGLAS DETALLADAS:\n"
    "BULLET DASH - Caso 1 (Prohibido en 1v1, permitido en glads): Es una variante del straight forward dash. La diferencia es el movimiento de cámara antes de confirmar el hit del frontdash, lo cual provoca que burle el block del enemigo.\n"
    "BULLET DASH - Caso 2 (Permitido siempre): Esta variante es 100% escapable y reaccionable, permitida en 1v1 y glads.\n\n"
    "STRAIGHT FORWARD DASH (Prohibido en 1v1, permitido en glads): Frontdash recto con nulo o mínimo movimiento de cámara. Baneado porque genera combates monótonos sin gamesense y da ventaja injusta a jugadores de bajo ping.\n\n"
    "SNEAKING EN 1V1 (Prohibido): Atacar sorpresivamente al rival después de un respawn se considera sneaking. Siempre tomar distancia antes de empezar el round.\n"
    "SNEAKING EN GLADS (Prohibido): Atacar al rival mientras termina o está terminando la animación del finisher de algún moveset se considera sneaking.\n"
    "EXCEPCION SNEAKING: NO se considera sneaking atacar a un jugador mientras hace un kill emote.\n\n"
    "METAL BAT: 5to puesto en jerarquía. Sin prohibiciones. Completamente usable en el competitivo.\n\n"
    "GAROU: 2do puesto. Move meta: Hunter's Grasp con TDS. Prohibidos: Ping Abuse Combo 1+3, Ping Abuse Combo 2+3, Ping Abuse Combo 1+2 recorrido.\n\n"
    "SAITAMA: 3er puesto. Move meta: Shove tercer movimiento. Prohibido: LordHeaven base.\n\n"
    "TAB GLITCH O LAGSWITCH: Autoronda para el enemigo en 1v1. Descalificación hasta la siguiente ronda en glads.\n\n"
    "PASSIVE STRIKE BASE: Jugabilidad extremadamente pasiva o dominantemente pasiva contra un jugador agresivo por 15 a 20 segundos resulta en passive strike.\n"
    "PASSIVE STRIKE RUNNING: Si el enemigo huye en 1v1 o glads entre 4-5 segundos se considera running y se penaliza con passive strike.\n"
    "PASSIVE STRIKE ANULADO: Si ambos jugadores tienen estilo pasivo predominante, no hay sanción para ninguno.\n\n"
    "PROGRAMAS PROHIBIDOS: Clumsy o cualquier programa que modifique o altere la latencia (lagswitch).\n"
    "PROGRAMAS PERMITIDOS: ExitLag está permitido. Bloxstrap permitido.\n"
    "MACROS: Las macros normales son válidas y legales. Si una macro otorga ventaja absurda o injusta será vetada. Prohibidas: emote cancel, aba true con lagswitch y macro combinados.\n\n"
    "DOUBLE RAGDOLL PROHIBIDO: Ejecutar double ragdoll en el 4to movimiento de Saitama específicamente está prohibido.\n"
    "DOUBLE RAGDOLL PERMITIDO: En cualquier otra situación como Twisted, Loop, Lethal, está permitido.\n\n"
    "SIDEDASH CANCEL CON MACRO O LAGSWITCH: Prohibido en cualquier contexto.\n\n"
    "ABA BASE (Prohibida): El aba base con m1 delay es ping abuse contra oponentes de alto ping, prohibida con o sin macro. Usar programas externos para ejecutar aba true como Clumsy está estrictamente prohibido.\n"
    "ABA ENDLAG (Permitida): Completamente escapable y bloqueable, permitida en el competitivo.\n\n"
    "HUNTER'S GRASP GAROU:\n"
    "- Flowing water o Lethal más grab recorrido: prohibido, es ping abuse e inescapable para jugadores de alta latencia.\n"
    "- Flowing water más Lethal recorrido: prohibido por las mismas razones.\n"
    "- Hunter's Grasp con side dash previo: permitido.\n"
    "- Flowing water más Lethal con side dash (Kyoto combo): permitido.\n\n"
    "LORDHEAVEN SAITAMA:\n"
    "- Base (m1 después de shove reseteando m1 con frontdash): prohibido.\n"
    "- Variante 1 (side dash más shove de primera): permitida.\n"
    "- Variante 2 (tumbar al suelo y ejecutar 4to movimiento de Saitama): permitida.\n\n"

    "TRYOUTS Y TRIALS:\n"
    "Son sesiones competitivas públicas o privadas. Tryout es para dar phases de Phase 1 Low o superior. Trial es para dar phases de Phase 1 Mid o superior.\n\n"

    "FFLAGS:\n"
    "Solo se permiten fflags autorizadas oficialmente por Roblox (Allowed List). Prohibido usar archivos externos o bypass para habilitar fflags no autorizadas. Prohibido remover límite de FPS (240fps), modificar físicas, MTU o alterar texturas no autorizadas. Bloxstrap nativo está permitido. Fishtrap, Voidstrap y variantes modificadas están prohibidas.\n\n"

    "LAGSWITCH (ACTUALIZADO): Cualquier forma de lagswitch en 1v1 o glads está prohibida. Incluye software externo para aumentar ping y tab glitch.\n\n"

    "MACROS (ACTUALIZADO): Solo se permiten macros para backdash cancel o insta ragdoll. Prohibidas: ABA Tech, Hybrid Forward Dash (side dash + frontdash), macros que manipulen la cámara para lethal tech, Lee twisted u otras.\n\n"

    "EXPLOITING: Prohibido sin excepción. Resulta en ban permanente del competitivo.\n\n"

    "PASSIVE STRIKE ACTUALIZADO: Un jugador recibe passive strike si pasa más de 12 segundos sin ejecutar un dash agresivo. El counterdash no es acción agresiva. Los passive strikes se acumulan. No generan redo ni autopoint, son advertencias. Al llegar a 3/3 el contrario gana automáticamente. Si ambos son pasivos, no se aplica.\n\n"

    "RUNNING: Correr por 4 segundos está prohibido. Usar side dash repetidas veces para tomar distancia también se considera running.\n\n"

    "PERSONAJES PERMITIDOS: Solo Saitama, Garou y Metal Bat.\n\n"

    "PUNISHMENTS POR TECHS PROHIBIDAS:\n"
    "- 1/3: Redo o autopoint si el jugador tiene 50% HP.\n"
    "- 2/3: Autopoint para el contrario.\n"
    "- 3/3: Autowin para el contrario.\n"
    "- Excepción: Si un jugador ejecuta Bullet o Straight Dash por error, no inicia combo y retoma su espacio, no es sancionado. Lo mismo aplica para Loop Dash.\n"
    "- Estas techs solo están prohibidas en 1v1 cross-region.\n\n"

    "TECHS PROHIBIDAS SAITAMA: Shove + M1 + Frontdash (M1 Reset), M1 Reset Bug con Consecutive Punch.\n\n"

    "TECHS PROHIBIDAS GAROU: Flowing + Hunter's Grasp, Lethal + Hunter's Grasp, Flowing + Lethal. Estas prohibiciones aplican solo cuando se ejecutan ambos ataques consecutivamente sin side dash. Con side dash están permitidas.\n\n"

    "TECHS PROHIBIDAS UNIVERSALES: ABA Tech, Double Ragdoll en el Uppercut de Saitama, Bullet y Straight Forward Dash (solo en 1v1 cross-region), Loop Dash y variantes (solo en 1v1 cross-region).\n\n"

    "LEADERBOARD:\n"
    "- Para entrar al leaderboard se necesita el rol de Phase 1. Se obtiene mediante una tryout de P1. Permite retar al Top 30.\n"
    "- Cooldowns: Si perdés, 7 días antes de volver a retar. Si ganás, 4 días antes de aceptar otro reto. El cooldown es opcional si ambos jugadores están de acuerdo.\n"
    "- Rango de desafío: Top 30-21 puede retar hasta 3 puestos arriba. Top 20-11 puede retar hasta 2 puestos arriba. Top 10-1 puede retar solo 1 puesto arriba.\n"
    "- Formatos permitidos: FT5 o FT10 estándar, FT5 cross-region, FT5 o 2 Sets.\n\n"

    "TRAINING:\n"
    "- Se organizan sesiones de Glads Training, normalmente por Wawa (Davidzouu).\n"
    "- Formato libre, con enfoque en técnicas como TDS y Spacing.\n"
    "- Los logs de training usan el mismo formato que los scores de Glads.\n\n"

    "CANALES IMPORTANTES:\n"
    "- suggestions: sugerir cambios al server o competitivo.\n"
    "- server-anncs: anuncios oficiales, torneos, cambios de reglas.\n"
    "- sae-anncs: anuncios de São Paulo y Sudamérica.\n"
    "- events: torneos por robux y eventos especiales.\n"
    "- polls: encuestas sobre el competitivo.\n"
    "- hall-of-shame: memes y momentos chistosos.\n"
    "- blacklist: lista pública de jugadores y clanes bloqueados del competitivo.\n"
    "- unblacklist: jugadores o clanes desblacklisteados.\n"
    "- phase-record: ranking actualizado de jugadores por phase y región (SAW/SAE).\n"
    "- Boosters reciben: más XP, rol exclusivo, permisos extra y acceso a tryouts privadas.\n\n"

    "SET SCORES:\n"
    "Los scores de 1v1 se registran con el comando >score. El formato incluye los jugadores, el score final, el ganador, las rondas jugadas, los referees y notas. Ejemplo: jugador A vs jugador B, score 6-1, con referees y cooldowns asignados automáticamente.\n\n"

    "SET ANNCS:\n"
    "Canal para anunciar partidas importantes, principalmente del Top 10 de LATAM o jugadores destacados.\n\n"

    "TOP 10 LATAM ACTUAL (SAE - São Paulo):\n"
    "1. Ayato - Phase 1 High Stable - São Paulo, Brasil - LOA\n"
    "2. MTZ - Phase 1 Mid Stable - São Paulo, Brasil - LOA\n"
    "3. Pekaiju - Phase 1 High Weak - São Paulo, Brasil - LOA\n"
    "4. Thalyson - Phase 1 Mid Weak - São Paulo, Brasil - No Cooldown\n"
    "5. Pudim - Phase 1 Low Strong - São Paulo, Brasil - En cooldown\n"
    "6. Kida Ego - Phase 1 Low Strong - São Paulo, Brasil - No Cooldown - Chile\n"
    "7. (Sin nombre) - Phase 1 Low Stable - Miami, Florida - En cooldown - Colombia\n"
    "8. Kay - Phase 1 Low Weak - São Paulo, Brasil - No Cooldown - Argentina\n"
    "9. Kur - Phase 1 Low Strong - São Paulo, Brasil - LOA - Chile\n"
    "10. Stray - Phase 1 Low Strong - São Paulo, Brasil - LOA - Chile\n\n"

    "MEJOR JUGADOR DEL COMPETITIVO TSB:\n"
    "Boomy, de TSBCC (TSB Clanning Community), es considerado el mejor jugador de todo el competitivo de TSB a nivel global.\n\n"

    "SOBRE EL BOT:\n"
    "Friity es asistente de TSBL (TSB LATAM). TSBCC significa 'TSB Clanning Community' y es una organización competitiva separada e independiente de TSBL, no una región ni un país. Si alguien pregunta sobre TSBCC, TSBSA, TSBEU, TSBNR, TSBASIA u otras organizaciones, aclarar que Friity solo tiene información sobre TSBL y no puede hablar con detalle de otras organizaciones, aunque sí puede mencionar que existen y que TSBCC es la Clanning Community.\n\n"

    "COMANDOS DEL BOT FRIITY:\n"
    "- >ask <pregunta>: Le hacés una pregunta a Friity y responde con info del clan o del competitivo de TSBL.\n"
    "- >tier <0-5|app> <low|mid|high> <weak|stable|strong> [@user] <sp|mi|da|cl|la> [note: texto]: Asigna roles de tier a un usuario. Solo lo pueden usar quienes tengan el rol TRYOUTER.\n"
    "- >poll <pregunta> | <opcion1> | <opcion2> [vote: N] [time: N unit]: Crea una encuesta. Solo en el canal de polls. Solo rol PollsEvent.\n"
    "- >info: Muestra tu perfil vinculado de Roblox con tu tier, región y streak.\n"
    "- >setuprules: Manda el embed de rules al canal de rules.\n"
    "- ?activity check <texto> @everyone: Lanza un activity check. Solo el owner del bot puede usarlo.\n"
    "Cuando alguien pregunta sobre estos comandos, explicá exactamente cómo funcionan según esta descripción. No inventes sintaxis ni funciones que no existen.\n\n"

    "TRIALS P1:\n"
    "Son sesiones de evaluación donde un tryouter testea a un jugador para determinar si merece una Phase 1.\n"
    "P1 Low Trial: para jugadores que podrían clasificar en Phase 1 Low.\n"
    "P1 Mid Trial: para jugadores que podrían clasificar en Phase 1 Mid.\n"
    "Los resultados se publican en los canales p1-low-trial-result y p1-mid-trial-result.\n\n"

    "SISTEMA DE PHASES (resumen):\n"
    "Phase 0 Nivel Supremo: Dominio total. Nivel máximo de LATAM.\n"
    "Phase 1 Nivel Avanzado: Skill alta y estable. Top LATAM/SA.\n"
    "Phase 2 Nivel Promedio: Jugadores consistentes, nivel estándar.\n"
    "Phase 3 Nivel en Crecimiento: Fundamentos claros pero irregulares.\n"
    "Phase 4 Principiante con Base: Entienden movimientos básicos.\n"
    "Phase 5 Nuevo en el competitivo: Recién empiezan.\n\n"

    "TIERS: HIGH casi listo para subir, MID posición estable, LOW en desarrollo.\n"
    "SUB-TIERS: STRONG cercano a ascenso, STABLE constante, WEAK en transición.\n\n"

    "COMANDO >tier: Formato: >tier [phase 0-5] [low/mid/high] [weak/stable/strong] [región opcional]\n"
    "Regiones: sp=São Paulo, mi=Miami, da=Dallas, la=Los Angeles.\n\n"

    "TRYOUTS: El tryouter puede dar hasta su propia phase. Límite máximo: 2 high strong. Comando: >phase [número] [tier] [sub-tier] @usuario\n\n"

    "CANALES DEL SERVIDOR:\n"
    "Welcome: welcome, exit, invite-tracker\n"
    "Anncs: server-annc, sub-annc, server-updates\n"
    "Info: rules, punishments, overview, role-guide, suggestions\n"
    "Host: tryouts, tryout-results, trainings, training-results, tryout-info, training-info\n"
    "Leaderboard: challenge-ticket, top-10, top-20, top-30, set-anncs, set-scores\n"
    "Global: general, hall-of-fame, memes, media, commands\n"
    "Staff: moderator-only, logs, warns, bans-blacklist\n\n"

    "TRYOUTS SISTEMA COMPLETO:\n"
    "Las Tryouts son pruebas de evaluación de nivel. Cualquier persona con el rol 'Skill Lookout' puede realizarlas. Se puede hacer una tryout cada 3 días. También se puede transferir una phase desde rankings externos admitidos como TSBBR o TSBL. Las tryouts de P1 se hacen en 2 sets de FT5. Si el jugador no pasa la prueba P1, debe esperar aproximadamente 2 semanas para volver a intentarlo.\n\n"

    "P1 APPLICANT:\n"
    "El rol P1 Applicant se da a quienes son admitidos para hacer la transición a P1 Low Weak. Para obtenerlo se necesita primero P2 High Strong. Cualquier Skill Lookout con al menos P1 Low Weak puede dar 1 App. Cualquier 1 App puede solicitar una Tryout a un P1 Manager.\n\n"

    "VOUCHS SISTEMA COMPLETO:\n"
    "Solo los jugadores 1 Low Strong+ pueden vouchear para 1 Low. No puedes vouchear a alguien con mayor phase que la tuya. Solo puedes vouchear hasta 2 tiers por encima del jugador. El vouch debe incluir una feat clara. Cantidad de vouchs por phase: 1 Low = 4 vouchs (phase mínima del voucher: 1 Low Strong), 1 Mid = 5 vouchs (mínimo: 1 Mid), 1 High = 7 vouchs (mínimo: 1 Mid Strong). Los vouchs para 1 Low Weak no son válidos (se requiere tryout oficial). Pueden realizarse UnVouchs con razón clara. Los vouchs fraudulentos resultan en veto indefinido. Cooldown de 7 días tras recibir vouchs y obtener nueva phase.\n\n"

    "AUTOWIN:\n"
    "El autowin se da cuando: el contrincante no se presenta a la hora acordada, el jugador no responde tickets al ser retado, entre otros. Cada autowin genera un strike/warn. Con 3/3 strikes se quita del top y no puede reincorporarse por 1 mes. En glads: clan ganador por autowin sin CD, clan perdedor con CD de 3 días.\n\n"

    "AUTOWIN STRIKE 1V1:\n"
    "Acumulación de 3/3. Con 3/3 el jugador es removido del competitivo y suspendido 2-4 semanas. Para reiniciar warns debe jugar 2 enfrentamientos (solo si tiene 2/3 strikes, cada enfrentamiento elimina 1 warn).\n\n"

    "GLADS FORMATO:\n"
    "Formato estándar 5v5, ampliable hasta 7v7 si ambos líderes acuerdan. FT mínimo FT3, máximo FT7. Máximo 2 jugadores en sublineup. Jugadores con ping superior a 150ms no pueden participar. Antigüedad mínima de 1 semana en el clan. No se permiten jugadores clanless. Las alts están prohibidas salvo justificación válida. Los aliados en lineup están prohibidos.\n\n"

    "GLADS CROSS REGION:\n"
    "Formato 5v5 ampliable hasta 7v7. Obligatoriamente FT3 en cada región correspondiente. Máximo 2 en sublineup.\n\n"

    "GLADS DESEMPATE:\n"
    "Si termina en empate, los líderes acuerdan nueva fecha. No puede realizarse el mismo día de la glad original.\n\n"

    "GLADS AUTOWIN STRIKES:\n"
    "Motivos: no presentarse en 15 minutos, no cumplir requisitos, uso de scripts/Clumsy/FFlags ilegales. 3/3 Autowin Strikes = eliminación del leaderboard + suspensión de 1 mes. Con 2/3 se pueden resetear completando 2 glads válidas.\n\n"

    "GLADS PUNISHMENTS:\n"
    "Por lagswitch/tab/techs prohibidas/sneaking: 1/3 respawn, 2/3 respawn, 3/3 expulsión. El straight forward dash, bullet dash, loop dashing NO están prohibidos en glads. Passive Strike en glads se acumula individualmente. No genera redo ni respawn. Con 3/3 el jugador queda expulsado.\n\n"

    "GLAD RULES:\n"
    "No sneaking (atacar durante o inmediatamente después del finisher). No aplica si el adversario hace kill emote. Máximo 2 jugadores extranjeros o norteamericanos por lineup (no aplica a latinos que viven fuera). Si un jugador abandona el server tras ser notificado de screenshare recibe 1 warn y posible invalidación de victoria.\n\n"

    "CLANES REQUISITOS:\n"
    "Mínimo 40 miembros. Lineup para ambas regiones (Miami y São Paulo). Nombre máximo 20 caracteres. Sistema interno de rangos. Actividad constante cada 21 días. Registro oficial en TSB LATAM. Lineup de 5 jugadores activos para glads.\n\n"

    "CLAN LEADERS Y MODERADORES:\n"
    "Máximo 2-3 moderadores por clan. Si un Clan Leader kickea a un moderador sin consultar = warn directo. Para kickear a un moderador sin sanción: el mod causa problemas, está inactivo, o excede el límite. Siempre informar al staff antes de kickear a un moderador.\n\n"

    "CLAN LEADERS BL:\n"
    "BL temporal: puede ceder el clan leader en 24 horas. BL permanente: debe ceder el clan leader y la propiedad obligatoriamente.\n\n"

    "MERGE:\n"
    "Fusión de dos o más clanes. Requiere acuerdo escrito entre líderes. Se puede tener co-liderazgo. Está prohibido tomar control sin consenso, banear al líder sin causa, o manipular decisiones. Si la merge se disuelve, el clan que se va pierde su posición anterior. Incumplimientos pueden resultar en suspensiones o blacklist.\n\n"

    "SPAR ZONE:\n"
    "Espacio para enfrentamientos amistosos. Comando: ?spar <link del servidor privado> <notas>. Solo se puede usar una vez cada 10 minutos.\n\n"

    "DIVISIÓN REGIONAL TSBL:\n"
    "Zona Este (East): Brasil, Argentina, Chile, Uruguay, Paraguay, Bolivia.\n"
    "Zona Oeste (West): Perú, Ecuador, Colombia, Venezuela, Las Guayanas, Panamá, Costa Rica, Nicaragua, El Salvador, Honduras, Guatemala, Belice, México (Cali o Texas), todos los latinos residentes en NA, Trinidad y Tobago, Jamaica, Cuba, República Dominicana, Puerto Rico, Islas menores del Caribe.\n\n"

    "COOLDOWN 1V1:\n"
    "Ganador: 4 días de cooldown. Perdedor: 7 días de cooldown. Se puede cancelar si ambos oponentes acuerdan. Durante cooldown se puede duckear sin penalización. Si un jugador pelea teniendo cooldown, el cooldown se reinicia completamente.\n\n"

    "COOLDOWN GLAD:\n"
    "Ambos clanes: 3 días de cooldown. Se puede cancelar si ambos líderes acuerdan. Se pueden organizar glads dentro del cooldown pero jugarse al terminar.\n\n"

    "APLAZAMIENTOS:\n"
    "Se puede posponer el desafío por un día por problemas personales o técnicos. Límite de 1 aplazamiento. Si no asiste al reprogramado, se declara victoria del oponente.\n\n"

    "FTS ACUERDOS:\n"
    "En PvP por TOP: mínimo FT5, máximo FT10. En Glad: mínimo FT3, máximo FT10. En glad se puede acordar cantidad de jugadores: mínimo 2-3, máximo 7 por lineup.\n\n"

    "REQUISITOS JUGADORES EN GLAD:\n"
    "7 días dentro del clan. Rol de lineup. Phase dentro del clan. Tag del clan o ningún tag. Al registrar un clan nuevo hay que esperar 7 días para jugar glads. En merge también se exigen 7 días.\n\n"

    "FACTOR CONFIANZA:\n"
    "Se toma en cuenta la relación entre las personas al momento de sancionar. Si dos personas tienen buena relación, la sanción será justa según dicha relación. Si no hay relación previa, la sanción se aplica normalmente.\n\n"

    "TOP 10 LATAM ACTUALIZADO (SAE - São Paulo):\n"
    "1. Ayato - Phase 1 High Stable - São Paulo, Brasil - LOA - Brasil\n"
    "2. MTZ - Phase 1 Mid Stable - São Paulo, Brasil - LOA - Brasil\n"
    "3. Pekaiju - Phase 1 High Weak - São Paulo, Brasil - LOA - Brasil\n"
    "4. Thalyson - Phase 1 Mid Weak - São Paulo, Brasil - No Cooldown - Brasil\n"
    "5. Pudim - Phase 1 Low Strong - São Paulo, Brasil - No Cooldown - Brasil\n"
    "6. Xain - Phase 1 Low Stable - Miami, Florida - LOA - Colombia\n"
    "7. Kay - Phase 1 Low Weak - São Paulo, Brasil - No Cooldown - Argentina\n"
    "8. Kur - Phase 1 Low Strong - São Paulo, Brasil - No Cooldown - Chile\n"
    "9. Stray - Phase 1 Low Strong - São Paulo, Brasil - LOA - Chile\n"
    "10. T4lent - Phase 1 Low Stable - São Paulo, Brasil - LOA - Brasil\n\n"

    "COUNTRY LEADERBOARD TSBL:\n"
    "1. Brasil - Best Player: Ayato - Performance Gap: 55/100\n"
    "2. Colombia - Performance Gap: 45/100\n"
    "3. México - Performance Gap: 35/100\n"
    "4. Peru - Performance Gap: 40/100\n"
    "5. República Dominicana - Performance Gap: 40/100\n"
    "6. Venezuela - Performance Gap: 35/100\n"
    "7. Chile - Best Player: Kur - Performance Gap: 35/100\n"
    "8. Ecuador - Performance Gap: 55/100\n"
    "9. Argentina - Best Player: Kay - Performance Gap: 30/100\n"
    "10. Uruguay - Performance Gap: 20/100\n\n"

    "GUIA COMPETITIVA TSB - COMO MEJORAR:\n"
    "El competitivo de TSB en alto nivel no se trata de velocidad sino de adaptabilidad. Los conceptos clave son: Adaptabilidad (cambiar estilo según el rival), Spacing (mantener distancia exacta y forzar errores), Counter Dash (atacar de segundo castigando el side dash del rival), Long Arm (side dash con M1 retrasado al último milisegundo), Baits (entrar y salir del rango para provocar side dashes al aire), Endlag abuse (usar frontdash calculando el impacto en los últimos fotogramas). En low ping (<60ms) retrasar los M1. En high ping (>140ms) jugar a la predicción y movimientos erráticos. Para romper el plateau: jugar a los extremos (semana agresiva, semana pasiva), estudiar a jugadores de élite como Boomy y Val, dominar movimientos incómodos. La práctica deliberada consiste en entrenar con un objetivo específico por sesión, no simplemente jugar horas.\n\n"

    "REGLAS SERVIDOR TSBL - SANCIONES GRAVES:\n"
    "Sexualización de menores leve: warn permanente. Contenido sensible (memes de normalización): BL 3 meses. Contenido grave (CSAM, grooming, distribución): blacklist permanente. Leak de cara desde fuente privada sin consentimiento con intención de burla: blacklist. Filtración de documentos personales (carnet de identidad, etc.): blacklist directa. Amenaza de doxx teniendo info personal: BL. Amenaza de filtración de cara o documentos: BL.\n\n"

    "CASOS GRISES - LEAK DE CARA:\n"
    "No es BL si el usuario compartió voluntariamente la imagen en canales públicos. Es BL si fue obtenida de forma privada, compartida sin consentimiento, editada para humillar, o difundida con intención de molestar. La intención prima sobre el origen de la imagen.\n\n"

    "WARN SISTEMA GENERAL:\n"
    "1 warn = advertencia. 3 warns = blacklist temporal de 1 mes. Los warns duran 1 mes. Faltas graves = sanción inmediata sin warns previos."
)


RULES_LANG_CHANNELS = {
    "es": 1489768820632588419,
    "en": 1489768537982500895,
    "pt": 1489769065135214704,
}


class RulesView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(discord.ui.Button(
            label="Punishments",
            style=discord.ButtonStyle.link,
            url="https://discord.com/channels/1447027458845970656/1487884455728124014",
            row=1,
        ))

    async def _grant_access(self, interaction: discord.Interaction, channel_id: int):
        channel = interaction.guild.get_channel(channel_id)
        if channel is None:
            await interaction.response.send_message("Channel not found.", ephemeral=True)
            return
        try:
            await channel.set_permissions(interaction.user, view_channel=True)
            link = f"https://discord.com/channels/{interaction.guild.id}/{channel_id}"
            await interaction.response.send_message(
                f"Access granted. Go to your rules channel: {link}", ephemeral=True
            )
        except discord.Forbidden:
            await interaction.response.send_message(
                "I don't have permission to manage channels.", ephemeral=True
            )

    @discord.ui.button(
        label="Español",
        style=discord.ButtonStyle.danger,
        custom_id="rules:espanol",
        emoji=discord.PartialEmoji(name="Esp", id=1489666661228347526),
        row=0,
    )
    async def button_espanol(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._grant_access(interaction, RULES_LANG_CHANNELS["es"])

    @discord.ui.button(
        label="English",
        style=discord.ButtonStyle.primary,
        custom_id="rules:english",
        emoji=discord.PartialEmoji(name="EEUU", id=1489667788820971730),
        row=0,
    )
    async def button_english(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._grant_access(interaction, RULES_LANG_CHANNELS["en"])

    @discord.ui.button(
        label="Português",
        style=discord.ButtonStyle.success,
        custom_id="rules:portugues",
        emoji=discord.PartialEmoji(name="emoji_40", id=1489666119689306276),
        row=0,
    )
    async def button_portugues(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._grant_access(interaction, RULES_LANG_CHANNELS["pt"])


PUNISHMENTS_GIF_URL = (
    "https://cdn.discordapp.com/attachments/1480321316996517930/1487927655377408050/"
    "c52b8af68ed3854f1d32164f6dc36dfe.gif?ex=69caec1d&is=69c99a9d"
    "&hm=7a24d722a674c1b764bb7ce97d1b0d036c90f74ecbbf3bb6d6e75c8cdede5968&"
)
PUNISHMENTS_THUMB_URL = (
    "https://cdn.discordapp.com/attachments/1480321316996517930/1487916616095236146/"
    "Screen_Recording_20250329_174623_Pinterest_1.gif?ex=69cae1d5&is=69c99055"
    "&hm=c5b467ccedff4e84db4c9aac93708bead9e4f2f5fbacc1f4cd0dec1f02cf666e&"
)
PUNISHMENTS_BANNER_URL = (
    "https://cdn.discordapp.com/attachments/1480321316996517930/1487923286418653364/"
    "81c0e896fbfd82440bcc57136f17f1a7_3.png?ex=69cae80b&is=69c9968b"
    "&hm=fd091ff1c94b7fac6c6892a01dbc46928889f988d53193b6b7324c74c1c77760&"
)
RULES_CHANNEL_LINK = "https://discord.com/channels/1447027458845970656/1451654847408373944"


class PunishmentsView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(discord.ui.Button(
            label="Rules",
            style=discord.ButtonStyle.link,
            url=RULES_CHANNEL_LINK,
            row=0,
        ))


REGION_ROLES: dict[int, str] = {
    1451256254445129939: "São Paulo, Brazil",
    1490499594575020214: "Dallas, Texas",
    1451256372971704411: "Miami, Florida",
    1490500556203098263: "Los Angeles, California",
    1475519241221308628: "Asia-Oceania",
    1475519201140539546: "Asia-Oceania",
}


async def _delete_after(msg: discord.Message, delay: float) -> None:
    await asyncio.sleep(delay)
    try:
        await msg.delete()
    except discord.HTTPException:
        pass


async def _discord_api_request(method: str, endpoint: str, payload: dict) -> dict:
    headers = {
        "Authorization": f"Bot {DISCORD_BOT_TOKEN}",
        "Content-Type": "application/json",
    }
    async with aiohttp.ClientSession() as session:
        call = session.post if method == "POST" else session.patch
        async with call(f"{DISCORD_API_BASE}{endpoint}", headers=headers, json=payload) as resp:
            try:
                return await resp.json()
            except Exception:
                return {}


async def _add_reaction(channel_id: int, message_id: str, emoji: str) -> None:
    import urllib.parse
    encoded = urllib.parse.quote(emoji, safe="")
    headers = {"Authorization": f"Bot {DISCORD_BOT_TOKEN}"}
    async with aiohttp.ClientSession() as session:
        async with session.put(
            f"{DISCORD_API_BASE}/channels/{channel_id}/messages/{message_id}/reactions/{encoded}/@me",
            headers=headers,
        ) as resp:
            pass


async def _interaction_callback(interaction: discord.Interaction, payload: dict) -> None:
    url = f"https://discord.com/api/v10/interactions/{interaction.id}/{interaction.token}/callback"
    headers = {
        "Authorization": f"Bot {DISCORD_BOT_TOKEN}",
        "Content-Type": "application/json",
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(url, headers=headers, json=payload) as resp:
            pass


class PollState:
    def __init__(
        self,
        poll_id: str,
        question: str,
        options: list[str],
        vote_goal: int | None,
        close_at: float | None,
        channel_id: int,
        accent_color: int,
    ):
        self.poll_id = poll_id
        self.question = question
        self.options = options
        self.vote_goal = vote_goal
        self.close_at = close_at
        self.channel_id = channel_id
        self.accent_color = accent_color
        self.message_id: str | None = None
        self.votes: dict[int, set[int]] = {i: set() for i in range(len(options))}
        self.user_vote: dict[int, int] = {}
        self.closed = False

    def winner_text(self) -> str:
        max_votes = max((len(v) for v in self.votes.values()), default=0)
        if max_votes == 0:
            return "No votes"
        winners = [self.options[i] for i, v in self.votes.items() if len(v) == max_votes]
        return f"{', '.join(winners)} ({max_votes} vote{'s' if max_votes != 1 else ''})"

    def winner_announcement(self) -> str:
        max_votes = max((len(v) for v in self.votes.values()), default=0)
        if max_votes == 0:
            return "The poll has closed with no votes."
        winners = [self.options[i] for i, v in self.votes.items() if len(v) == max_votes]
        winner_label = ", ".join(f"**{w}**" for w in winners)
        suffix = (
            "It's a tie — both options finish level!"
            if len(winners) > 1
            else "Congratulations to everyone who voted for it!"
        )
        return f"Winner: {winner_label} — {suffix}"


def _poll_time_remaining(close_at: float) -> str:
    remaining = max(0, int(close_at - datetime.now(timezone.utc).timestamp()))
    hours, rem = divmod(remaining, 3600)
    minutes, seconds = divmod(rem, 60)
    if hours > 0:
        return f"{hours}h {minutes}m {seconds}s"
    if minutes > 0:
        return f"{minutes}m {seconds}s"
    return f"{seconds}s"


def build_poll_components(state: PollState, final: bool = False) -> list[dict]:
    total = sum(len(v) for v in state.votes.values())

    container_inner: list[dict] = [
        {"type": 10, "content": f"### ➤ {state.question}"},
        {"type": 14, "spacing": 1},
    ]

    for i, option in enumerate(state.options):
        count = len(state.votes[i])
        container_inner.append({
            "type": 9,
            "components": [{"type": 10, "content": f"{option} — {count} vote{'s' if count != 1 else ''}"}],
            "accessory": {
                "type": 2,
                "style": 2,
                "label": f"{option} ({count})",
                "custom_id": f"poll:{state.poll_id}:vote:{i}",
                "disabled": final,
            },
        })

    container_inner.append({"type": 14, "spacing": 1})

    if final:
        container_inner.append({
            "type": 10,
            "content": f"・ Poll closed | Winner: {state.winner_text()}",
        })
    elif state.vote_goal:
        container_inner.append({
            "type": 10,
            "content": f"・ Vote goal: {total}/{state.vote_goal}",
        })
    elif state.close_at:
        container_inner.append({
            "type": 10,
            "content": f"・ Time remaining: {_poll_time_remaining(state.close_at)}",
        })

    container_inner.append({"type": 10, "content": f"||<@&{POLL_PING_ROLE_ID}>||"})

    components: list[dict] = [
        {"type": 17, "accent_color": state.accent_color, "components": container_inner},
        {
            "type": 1,
            "components": [{
                "type": 2,
                "style": 2,
                "label": "Close Poll",
                "custom_id": f"poll:{state.poll_id}:close",
                "disabled": final,
            }],
        },
    ]

    return components


async def _do_close_poll(
    state: PollState,
    interaction: discord.Interaction | None = None,
) -> None:
    if state.closed:
        if interaction:
            await _interaction_callback(interaction, {
                "type": 4,
                "data": {"content": "This poll is already closed.", "flags": 64},
            })
        return

    state.closed = True
    active_polls.pop(state.poll_id, None)
    components = build_poll_components(state, final=True)

    if interaction:
        await _interaction_callback(interaction, {
            "type": 7,
            "data": {"flags": COMPONENTS_V2_FLAG, "components": components},
        })
    elif state.message_id:
        await _discord_api_request(
            "PATCH",
            f"/channels/{state.channel_id}/messages/{state.message_id}",
            {"flags": COMPONENTS_V2_FLAG, "components": components},
        )

    channel = client.get_channel(state.channel_id)
    if channel:
        await channel.send(state.winner_announcement())


async def _auto_close_poll(poll_id: str, seconds: float) -> None:
    await asyncio.sleep(seconds)
    state = active_polls.get(poll_id)
    if state and not state.closed:
        await _do_close_poll(state)


class ActivityCheckState:
    def __init__(
        self,
        check_id: str,
        guild_id: int,
        original_channel_id: int,
    ):
        self.check_id = check_id
        self.guild_id = guild_id
        self.original_channel_id = original_channel_id
        self.original_message_id: str | None = None
        self.checkers: dict[int, str] = {}


def _load_streaks() -> dict:
    if STREAKS_FILE.exists():
        try:
            return json.loads(STREAKS_FILE.read_text())
        except Exception:
            return {}
    return {}


def _save_streaks(data: dict) -> None:
    STREAKS_FILE.write_text(json.dumps(data, indent=2))


# ---------------- User registry ----------------

def _load_user_registry() -> None:
    """Carga el registro persistido a memoria. Si falla, arranca vacio."""
    global _user_registry
    try:
        if USER_REGISTRY_FILE.exists():
            _user_registry = json.loads(USER_REGISTRY_FILE.read_text())
            total = sum(len(g.get("users", {})) for g in _user_registry.values())
            print(f"[registry] Loaded {total} users across {len(_user_registry)} guild(s)")
        else:
            _user_registry = {}
    except Exception as e:
        print(f"[registry] load failed: {e}")
        _user_registry = {}


def _save_user_registry(force: bool = False) -> None:
    """Guarda a disco. Debouncea escribiendo cada N llamadas salvo que force=True."""
    global _registry_dirty_count
    _registry_dirty_count += 1
    if not force and _registry_dirty_count < _REGISTRY_SAVE_EVERY:
        return
    _registry_dirty_count = 0
    try:
        USER_REGISTRY_FILE.write_text(json.dumps(_user_registry, indent=2, default=str))
    except Exception as e:
        print(f"[registry] save failed: {e}")


def _ensure_guild_entry(guild_id: int, name: str | None = None) -> dict:
    gkey = str(guild_id)
    gentry = _user_registry.get(gkey)
    if gentry is None:
        gentry = {"name": name or "", "users": {}, "updated_at": ""}
        _user_registry[gkey] = gentry
    if name:
        gentry["name"] = name
    return gentry


def update_user_in_registry(
    member,
    guild=None,
    bump_last_seen: bool = True,
) -> None:
    """Crea o actualiza la entrada de un user en el registry.

    - member: discord.Member o discord.User
    - guild: discord.Guild (si es None, intenta member.guild)
    - bump_last_seen: si True, actualiza el last_seen a ahora
    """
    if guild is None:
        guild = getattr(member, "guild", None)
    if guild is None:
        return
    try:
        gentry = _ensure_guild_entry(guild.id, guild.name)
        now_iso = datetime.now(timezone.utc).isoformat()
        uid = str(member.id)
        existing = gentry["users"].get(uid, {})
        joined_at = existing.get("joined_at")
        m_joined = getattr(member, "joined_at", None)
        if m_joined is not None:
            try:
                joined_at = m_joined.isoformat()
            except Exception:
                pass
        roles = [
            {"id": r.id, "name": r.name}
            for r in getattr(member, "roles", [])
            if getattr(r, "name", None) and r.name != "@everyone"
        ]
        entry = {
            "username": getattr(member, "name", str(member.id)),
            "display_name": getattr(member, "display_name", None)
                or getattr(member, "global_name", None)
                or getattr(member, "name", str(member.id)),
            "is_bot": bool(getattr(member, "bot", False)),
            "joined_at": joined_at,
            "roles": roles,
            "last_seen": now_iso if bump_last_seen else existing.get("last_seen"),
            "streak": existing.get("streak", 0),
        }
        gentry["users"][uid] = entry
        gentry["updated_at"] = now_iso
        _save_user_registry(force=False)
    except Exception as e:
        print(f"[registry] update_user failed for {getattr(member, 'id', '?')}: {e}")


async def snapshot_all_users(guild) -> int:
    """Snapshot completo de miembros de un guild al registry. Guarda a disco al final."""
    gentry = _ensure_guild_entry(guild.id, guild.name)
    count = 0
    try:
        members_iter = list(getattr(guild, "members", []) or [])
        if len(members_iter) <= 1:
            try:
                members_iter = [m async for m in guild.fetch_members(limit=None)]
            except Exception as e:
                print(f"[registry] fetch_members failed for {guild.id}: {e}")
        for member in members_iter:
            update_user_in_registry(member, guild, bump_last_seen=False)
            count += 1
    except Exception as e:
        print(f"[registry] snapshot failed for {guild.id}: {e}")
    _save_user_registry(force=True)
    print(f"[registry] Snapshotted {count} users in '{guild.name}' (id {guild.id})")
    return count


def sync_streak_in_registry(user_id: int, streak: int) -> None:
    """Propaga el streak actualizado al registry (llamar tras cambiar streaks.json)."""
    uid = str(user_id)
    for gentry in _user_registry.values():
        entry = gentry.get("users", {}).get(uid)
        if entry is not None:
            entry["streak"] = streak
    _save_user_registry(force=False)


def _resolve_users_by_name(
    text: str,
    guild_id: int,
    limit: int = 5,
) -> list[int]:
    """Busca usuarios del registry que matcheen por username/display_name (case-insensitive).

    Prioriza matches exactos de token, despues substring. Retorna ids unicos (max `limit`).
    Filtra bots. Solo considera tokens de 3+ caracteres para evitar ruido.
    """
    if not text:
        return []
    gentry = _user_registry.get(str(guild_id))
    if not gentry:
        return []
    users = gentry.get("users") or {}
    if not users:
        return []

    # Extraer tokens del texto, filtrar stopwords comunes y tokens cortos
    raw_tokens = re.findall(r"[\w\-_.áéíóúñÁÉÍÓÚÑ]+", text.lower())
    stop = {
        "que", "quien", "quién", "como", "cómo", "cuando", "cuándo",
        "donde", "dónde", "sobre", "para", "dime", "dame", "info",
        "clan", "server", "servidor", "miembro", "miembros", "usuario",
        "usuarios", "user", "users", "tell", "about", "know", "what",
        "who", "why", "when", "where", "how", "the", "and", "can",
        "you", "your", "ask", "please",
    }
    tokens = [t for t in raw_tokens if len(t) >= 3 and t not in stop]
    if not tokens:
        return []

    exact: list[int] = []
    sub: list[int] = []
    for uid_str, entry in users.items():
        if entry.get("is_bot"):
            continue
        uname = (entry.get("username") or "").lower()
        dname = (entry.get("display_name") or "").lower()
        uname_tokens = set(re.findall(r"[\w\-_.áéíóúñ]+", uname))
        dname_tokens = set(re.findall(r"[\w\-_.áéíóúñ]+", dname))
        all_tokens = uname_tokens | dname_tokens
        try:
            uid_int = int(uid_str)
        except ValueError:
            continue
        for tok in tokens:
            if tok in all_tokens:
                if uid_int not in exact:
                    exact.append(uid_int)
                break
            if len(tok) >= 4 and (tok in uname or tok in dname):
                if uid_int not in sub:
                    sub.append(uid_int)
                break

    merged: list[int] = []
    for lst in (exact, sub):
        for uid in lst:
            if uid not in merged:
                merged.append(uid)
            if len(merged) >= limit:
                return merged
    return merged


def format_user_registry_entry(user_id: int, guild_id: int | None = None) -> str | None:
    """Formatea la entrada del user para pasarla al LLM. Devuelve None si no existe."""
    uid = str(user_id)
    entry = None
    if guild_id is not None:
        entry = _user_registry.get(str(guild_id), {}).get("users", {}).get(uid)
    if entry is None:
        for gentry in _user_registry.values():
            entry = gentry.get("users", {}).get(uid)
            if entry is not None:
                break
    if entry is None:
        return None
    roles_str = ", ".join(r["name"] for r in entry.get("roles") or []) or "sin roles destacados"
    return (
        f"display_name={entry.get('display_name')}, username={entry.get('username')}, "
        f"id={user_id}, is_bot={entry.get('is_bot', False)}, "
        f"joined_at={entry.get('joined_at') or '?'}, last_seen={entry.get('last_seen') or '?'}, "
        f"streak={entry.get('streak', 0)}, roles=[{roles_str}]"
    )


def _save_activity_state() -> None:
    try:
        data = {
            "current_check_id": current_check_id,
            "checks": {
                msg_id: {
                    "check_id": st.check_id,
                    "guild_id": st.guild_id,
                    "original_channel_id": st.original_channel_id,
                    "original_message_id": st.original_message_id,
                    "checkers": {str(uid): name for uid, name in st.checkers.items()},
                }
                for msg_id, st in active_activity_checks.items()
            },
        }
        ACTIVITY_STATE_FILE.write_text(json.dumps(data, indent=2))
    except Exception as e:
        print(f"[activity] save state failed: {e}")


def _load_activity_state() -> None:
    global current_check_id
    try:
        if not ACTIVITY_STATE_FILE.exists():
            return
        data = json.loads(ACTIVITY_STATE_FILE.read_text())
        current_check_id = data.get("current_check_id")
        for msg_id, info in (data.get("checks") or {}).items():
            state = ActivityCheckState(
                check_id=info["check_id"],
                guild_id=int(info["guild_id"]),
                original_channel_id=int(info["original_channel_id"]),
            )
            state.original_message_id = info.get("original_message_id")
            state.checkers = {
                int(uid): name
                for uid, name in (info.get("checkers") or {}).items()
            }
            active_activity_checks[msg_id] = state
        print(
            f"[activity] Restored {len(active_activity_checks)} activity check(s) "
            f"(current_check_id={current_check_id})"
        )
    except Exception as e:
        print(f"[activity] load state failed: {e}")


def get_streak(uid: int) -> int:
    data = _load_streaks()
    return data.get(str(uid), {}).get("streak", 0)


async def _assign_streak_role(member: discord.Member, streak: int) -> None:
    guild = member.guild
    target_name = f"Streak {streak}" if streak > 0 else None

    # Remove any other "Streak N" roles the member currently has.
    roles_to_remove: list[discord.Role] = [
        role
        for role in list(member.roles)
        if _STREAK_ROLE_NAME_RE.match(role.name) and role.name != target_name
    ]

    target_role: discord.Role | None = None
    if target_name:
        target_role = discord.utils.get(guild.roles, name=target_name)
        if target_role is None:
            try:
                target_role = await guild.create_role(
                    name=target_name,
                    reason=f"User reached streak {streak}",
                )
            except Exception as e:
                print(f"[streak] Could not create role {target_name}: {e}")
                target_role = None

    try:
        if roles_to_remove:
            await member.remove_roles(*roles_to_remove, reason="Streak role update")
        if target_role and target_role not in member.roles:
            await member.add_roles(target_role, reason=f"Streak {streak}")
    except Exception as e:
        print(f"[streak] Role assign error for {member}: {e}")


def build_activity_container(_check_id: str) -> list[dict]:
    return [
        {
            "type": 17,
            "components": [
                {"type": 10, "content": "Tap here ✅"},
            ],
        },
        {
            "type": 1,
            "components": [
                {
                    "type": 2,
                    "style": 2,
                    "label": "Users",
                    "emoji": {"name": "emoji_49", "id": "1491920857134530783"},
                    "custom_id": "activity:users",
                },
                {
                    "type": 2,
                    "style": 2,
                    "label": "Streak",
                    "emoji": {"name": "emoji_50", "id": "1491941471249764453"},
                    "custom_id": "activity:streak",
                },
            ],
        },
    ]


async def handle_activity_check(message: discord.Message):
    global current_check_id

    if message.author.id != BOT_OWNER_ID:
        return

    if "@everyone" not in message.content:
        return

    match = re.match(r"\?activity\s+check\s*(.*)", message.content, re.IGNORECASE | re.DOTALL)
    if not match:
        return

    check_id = str(uuid.uuid4())[:8]

    async with streak_lock:
        data = _load_streaks()
        prev_check_id = current_check_id
        if prev_check_id:
            for uid_str, entry in data.items():
                uid = int(uid_str)
                if uid in ACTIVITY_EXCLUDED_IDS:
                    continue
                if entry.get("last_check_id") != prev_check_id and entry.get("streak", 0) > 0:
                    entry["streak"] = 0
                    entry.pop("last_check_id", None)
        current_check_id = check_id
        _save_streaks(data)

    state = ActivityCheckState(
        check_id=check_id,
        guild_id=message.guild.id,
        original_channel_id=message.channel.id,
    )
    state.original_message_id = str(message.id)
    active_activity_checks[str(message.id)] = state

    _save_activity_state()

    asyncio.create_task(_add_reaction(message.channel.id, str(message.id), "✅"))

    await _discord_api_request(
        "POST",
        f"/channels/{message.channel.id}/messages",
        {"flags": COMPONENTS_V2_FLAG, "components": build_activity_container(check_id)},
    )


@client.event
async def on_ready():
    global BOT_OWNER_ID
    app_info = await client.application_info()
    BOT_OWNER_ID = app_info.owner.id
    client.add_view(RulesView())
    client.add_view(PunishmentsView())
    client.add_view(LinkRobloxView())
    _load_activity_state()
    _load_user_registry()
    # Snapshot completo de cada guild al arrancar
    for guild in client.guilds:
        try:
            await snapshot_all_users(guild)
        except Exception as e:
            print(f"[registry] startup snapshot failed for {guild.id}: {e}")
    print(f"Logged in as {client.user} (ID: {client.user.id})")
    print(f"Owner ID cached: {BOT_OWNER_ID}")
    print("Bot is ready. Listening for >ask, >tier, >poll, >setuprules, >info, ?activity check commands.")


@client.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    # Mantener el registry actualizado con el autor del mensaje
    if message.guild is not None:
        try:
            update_user_in_registry(message.author, message.guild, bump_last_seen=True)
        except Exception as e:
            print(f"[registry] on_message update failed: {e}")

    if message.content.startswith(">ask"):
        await handle_ask(message)
    elif message.content.startswith(">tier"):
        await handle_tier(message)
    elif message.content.startswith(">poll"):
        await handle_poll(message)
    elif message.content.startswith(">setuprules"):
        await handle_setuprules(message)
    elif message.content.startswith(">rulesv2"):
        await handle_rulesv2(message)
    elif message.content.startswith(">info"):
        await handle_info(message)
    elif message.content.lower().startswith("?activity"):
        await handle_activity_check(message)


@client.event
async def on_interaction(interaction: discord.Interaction):
    if interaction.type != discord.InteractionType.component:
        return

    custom_id: str = (interaction.data or {}).get("custom_id", "")

    # StringSelect del container de rules (>rulesv2): responde efimero con link al canal
    if custom_id == "menu_canales":
        values = (interaction.data or {}).get("values") or []
        if not values:
            await _interaction_callback(interaction, {
                "type": 4,
                "data": {"content": "You didn't select any channel.", "flags": 64},
            })
            return
        chan_id = values[0]
        await _interaction_callback(interaction, {
            "type": 4,
            "data": {
                "content": f"Go to channel: <#{chan_id}>",
                "flags": 64,
            },
        })
        return

    parts = custom_id.split(":")
    if len(parts) < 2:
        return

    prefix = parts[0]

    if prefix == "poll":
        poll_id = parts[1]
        action = parts[2]
        state = active_polls.get(poll_id)

        if state is None or state.closed:
            await _interaction_callback(interaction, {
                "type": 4,
                "data": {"content": "This poll is no longer active.", "flags": 64},
            })
            return

        if action == "vote" and len(parts) >= 4:
            option_index = int(parts[3])
            user_id = interaction.user.id
            prev = state.user_vote.get(user_id)

            if prev == option_index:
                state.votes[option_index].discard(user_id)
                del state.user_vote[user_id]
            else:
                if prev is not None:
                    state.votes[prev].discard(user_id)
                state.votes[option_index].add(user_id)
                state.user_vote[user_id] = option_index

            total = sum(len(v) for v in state.votes.values())
            if state.vote_goal and total >= state.vote_goal:
                await _do_close_poll(state, interaction=interaction)
            else:
                await _interaction_callback(interaction, {
                    "type": 7,
                    "data": {
                        "flags": COMPONENTS_V2_FLAG,
                        "components": build_poll_components(state),
                    },
                })

        elif action == "close":
            member_role_ids = {r.id for r in getattr(interaction.user, "roles", [])}
            if POLL_ROLE_ID not in member_role_ids:
                await _interaction_callback(interaction, {
                    "type": 4,
                    "data": {
                        "content": "You don't have permission to close this poll.",
                        "flags": 64,
                    },
                })
                return
            await _do_close_poll(state, interaction=interaction)

    elif prefix == "activity":
        action = parts[1]
        EPHEMERAL_V2 = 64 | COMPONENTS_V2_FLAG

        if action == "users":
            state = next(
                (s for s in active_activity_checks.values() if s.check_id == current_check_id),
                None,
            ) if current_check_id else None

            name_rows: list[dict] = (
                [{"type": 10, "content": f"**{n}**"} for n in state.checkers.values()]
                if state and state.checkers
                else [{"type": 10, "content": "*No one has checked in yet.*"}]
            )

            components = [
                {
                    "type": 17,
                    "components": [
                        {"type": 10, "content": "### Activity Check — Users"},
                        {"type": 14},
                        *name_rows,
                        {"type": 14},
                        {
                            "type": 9,
                            "components": [{"type": 10, "content": "Updating... rewards coming soon"}],
                            "accessory": {
                                "type": 2,
                                "style": 2,
                                "label": "Rewards",
                                "custom_id": "activity:rewards",
                            },
                        },
                    ],
                },
            ]
            await _interaction_callback(interaction, {
                "type": 4,
                "data": {"flags": EPHEMERAL_V2, "components": components},
            })
            return

        if action == "streak":
            data = _load_streaks()
            leaderboard = sorted(
                [
                    (int(uid), entry.get("streak", 0))
                    for uid, entry in data.items()
                    if int(uid) not in ACTIVITY_EXCLUDED_IDS and entry.get("streak", 0) > 0
                ],
                key=lambda x: x[1],
                reverse=True,
            )[:5]
            guild = client.get_guild(interaction.guild_id) if interaction.guild_id else None
            rows: list[dict] = []
            for rank, (uid, cnt) in enumerate(leaderboard):
                member = guild.get_member(uid) if guild else None
                name = member.display_name if member else str(uid)
                rows.append({
                    "type": 10,
                    "content": (
                        f"<:emoji_50:1491941471249764453> **{name}** — "
                        f"{cnt} streak{'s' if cnt != 1 else ''}"
                    ),
                })
            if not rows:
                rows = [{"type": 10, "content": "*No streak data yet.*"}]

            components = [
                {
                    "type": 17,
                    "components": [
                        {"type": 10, "content": "### Streak Top 5"},
                        {"type": 14},
                        *rows,
                    ],
                },
            ]
            await _interaction_callback(interaction, {
                "type": 4,
                "data": {"flags": EPHEMERAL_V2, "components": components},
            })
            return

        if action == "rewards":
            await _interaction_callback(interaction, {
                "type": 4,
                "data": {"content": "Updating... rewards coming soon.", "flags": 64},
            })
            return


@client.event
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent):
    if payload.user_id == client.user.id:
        return
    if str(payload.emoji) != "✅":
        return
    if payload.user_id in ACTIVITY_EXCLUDED_IDS:
        return

    msg_id = str(payload.message_id)
    state = active_activity_checks.get(msg_id)
    if state is None:
        return

    display_name = (
        payload.member.display_name
        if payload.member
        else str(payload.user_id)
    )
    state.checkers[payload.user_id] = display_name

    async with streak_lock:
        data = _load_streaks()
        uid_str = str(payload.user_id)
        entry = data.setdefault(uid_str, {"streak": 0})
        if entry.get("last_check_id") != state.check_id:
            entry["streak"] = entry.get("streak", 0) + 1
            entry["last_check_id"] = state.check_id
        new_streak = entry["streak"]
        _save_streaks(data)

    _save_activity_state()
    sync_streak_in_registry(payload.user_id, new_streak)

    if payload.member:
        try:
            update_user_in_registry(payload.member, payload.member.guild, bump_last_seen=True)
        except Exception:
            pass
        asyncio.create_task(_assign_streak_role(payload.member, new_streak))


@client.event
async def on_raw_reaction_remove(payload: discord.RawReactionActionEvent):
    if payload.user_id == client.user.id:
        return
    if str(payload.emoji) != "✅":
        return
    if payload.user_id in ACTIVITY_EXCLUDED_IDS:
        return

    msg_id = str(payload.message_id)
    state = active_activity_checks.get(msg_id)
    if state is None:
        return

    state.checkers.pop(payload.user_id, None)
    _save_activity_state()

    async with streak_lock:
        data = _load_streaks()
        uid_str = str(payload.user_id)
        entry = data.get(uid_str)
        if entry and entry.get("last_check_id") == state.check_id:
            entry["streak"] = max(0, entry.get("streak", 1) - 1)
            entry.pop("last_check_id", None)
            new_streak = entry["streak"]
            _save_streaks(data)
        else:
            new_streak = entry.get("streak", 0) if entry else 0

    sync_streak_in_registry(payload.user_id, new_streak)

    guild = client.get_guild(payload.guild_id)
    if guild:
        member = guild.get_member(payload.user_id)
        if member:
            try:
                update_user_in_registry(member, guild, bump_last_seen=True)
            except Exception:
                pass
            asyncio.create_task(_assign_streak_role(member, new_streak))


_MEMBER_KEYWORDS = re.compile(
    r"\b(members?\w*|who is|who are|clan members?|list members?|how many members?|"
    r"members? with role|players?\w*|people\w*|users?\w*|quienes?\w*|"
    r"miembros?\w*|cuant[oa]s?\w*|lista\w*|jugadores?\w*|personas?\w*)\b",
    re.IGNORECASE,
)

_ROLE_KEYWORDS = re.compile(
    r"\b(roles?\w*|roless?|rol\w*|what roles?|list roles?|que roles?|"
    r"cuales? roles?|cuantos? roles?|lista de roles?|"
    r"rank\w*|tier\w*|phase\w*)\b",
    re.IGNORECASE,
)

_CHANNEL_KEYWORDS = re.compile(
    r"\b(channels?\w*|canales?\w*|canal\w*|what channels?|list channels?|"
    r"que canales?|cuales? canales?|donde (esta|hay)|where is)\b",
    re.IGNORECASE,
)

_STAFF_KEYWORDS = re.compile(
    r"\b(mod\w*|staff\w*|moderator\w*|moderador\w*|tryouter\w*|"
    r"admin\w*|owner\w*|voucher\w*|manager\w*|"
    r"como ser\w*|how to be\w*|requisitos?|requirements?|"
    r"como (?:me |se |)hago|como (?:puedo |)ser|"
    r"como (?:me |se |)convierto|how (?:do i |can i |to )become)\b",
    re.IGNORECASE,
)

_ROLE_FILTER_RE = re.compile(
    r"(?:with role|con rol|rol)\s+[\"']?(.+?)[\"']?\s*(?:\?|$)",
    re.IGNORECASE,
)

_CHANNEL_HISTORY_KEYWORDS = re.compile(
    r"\b(que dijo|que escribio|que escribió|que puso|que coment(o|ó)|"
    r"dijo|escribio|escribió|what did|who said|someone said|"
    r"alguien dijo|ultimos? mensajes?|últimos? mensajes?|"
    r"mensajes? recientes?|recent messages?|chat reciente|"
    r"que hablaron|de que hablan|de qué hablan)\b",
    re.IGNORECASE,
)

_WEB_SEARCH_KEYWORDS = re.compile(
    r"\b(busca(?:r|lo|me)?|googlea(?:r|lo)?|google|search|"
    r"lo podrias? buscar|lo podés buscar|podrias? buscar|podés buscar|"
    r"que significa|qué significa|significado de|"
    r"que es (?:el |la )?meme|qué es (?:el |la )?meme|que es fomo|qué es fomo|"
    r"en (?:el |la )?internet|en google|en la web|en tik ?tok)\b",
    re.IGNORECASE,
)

CRITICAL_RULES = (
    "\n\n========= REGLAS ABSOLUTAS / ABSOLUTE RULES =========\n"
    "0) BREVEDAD OBLIGATORIA: respondes en 1-3 oraciones maximo. NO des textos largos ni biblias.\n"
    "   Solo te extendes si el usuario pide explicitamente 'explicame en detalle', 'dame todos los detalles',\n"
    "   'lista completa', etc. Por defecto: directo, corto, sin relleno ni disclaimers.\n"
    "1) IDENTIDAD POR DEFECTO: sos el bot del CLAN Celestials Dragons. La mayoria de las preguntas son sobre\n"
    "   el clan, su servidor, sus miembros, sus canales, sus rules internas, sus anuncios, activity, streaks, etc.\n"
    "   Responde SIEMPRE enfocado en el clan, con la info del servidor Celestials Dragons.\n"
    "2) SEPARACION CLAN vs TSBL: NO mezcles info de TSBL con info del clan. SOLO hablas de TSBL si el usuario\n"
    "   usa explicitamente al menos UNA de estas palabras: TSBL, TSB, TSBCC, phase, phases, tier, tiers,\n"
    "   glad, glads, gladiador, tryout, tryouts, trial, trials, vouch, vouchs, top 10 sae, top 10 saw,\n"
    "   phase-record, boomy, ayato, saitama, garou, metal bat, lagswitch, passive strike, aba, hunter grasp,\n"
    "   lordheaven, bullet dash, leaderboard de TSBL, competitivo. Si NO aparecen, responde SOLO del clan\n"
    "   y no menciones TSBL ni phases/tiers/glads aunque te parezca relacionado.\n"
    "3) NO INVENTAR JAMAS. NEVER invent acronyms, names, dates, numbers, tops, phases, clans, tournaments, or any data.\n"
    "   Si no sabes el significado exacto de una sigla, NO la completes con palabras que suenen parecidas.\n"
    "   Si el usuario pregunta por un dato dinamico (top 10, miembros actuales, anuncios, reglas vigentes, resultados, etc.)\n"
    "   y NO tenes ese dato en la seccion '[LIVE DATA - ...]', deci claramente 'no tengo ese dato en tiempo real' o\n"
    "   'necesito revisar el canal X, no lo tengo ahora'. Preferir decir 'no se' antes que inventar.\n"
    "4) SIGLAS OFICIALES (NO existen otras):\n"
    "   - TSB  = The Strongest Battlegrounds (el juego de Roblox).\n"
    "   - TSBL = TSB LATAM (la liga competitiva de LATAM).\n"
    "   - TSBCC = TSB Clanning Community.\n"
    "   Prohibido inventar otro significado (por ejemplo 'The Strongest Brawlers Legend' es INCORRECTO).\n"
    "5) IDIOMA: siempre respondes EN EL MISMO IDIOMA que escribio el usuario en este ultimo mensaje.\n"
    "   Si escribio en ingles -> responder SOLO en ingles. Si en portugues -> SOLO portugues. Si en espanol -> SOLO espanol.\n"
    "   No mezcles idiomas. No traduzcas si no te lo piden. Ignora el idioma del historial previo.\n"
    "6) WEB: NO digas 'busque en internet' ni cites fuentes web a menos que haya una seccion '[LIVE DATA - Resultados de busqueda web ...]'.\n"
    "   Si no hay resultados web cargados, significa que el usuario no pidio busqueda: contesta SOLO con tu conocimiento del clan/servidor.\n"
    "7) FUENTES DE VERDAD: cuando haya secciones '[LIVE DATA - ...]', esa es la unica verdad para esa pregunta. Copia nombres y numeros tal cual.\n"
    "8) Si el tema requiere datos de un canal (top 10, rules, anncs, phase-record, blacklist, etc.) y no hay datos de ese canal\n"
    "   en los [LIVE DATA], deci al usuario que revise el canal o que le mencione el canal con # para que puedas leerlo.\n"
    "9) STREAK: es el contador de participacion en activity checks del clan. Cada vez que un usuario reacciona con\n"
    "   el check a un activity check nuevo, su streak sube en 1. Si se saltea un activity check, su streak vuelve a 0.\n"
    "   Esto es del clan Celestials Dragons, no de TSBL. El comando para lanzarlo es '?activity check' (solo el owner).\n"
    "10) PROHIBIDO decir 'no tengo acceso a los canales/roles/miembros del servidor'. SI TENES ACCESO via Discord API.\n"
    "    Si un dato no esta en [LIVE DATA], NO digas que falta acceso. Deci 'no lo encontre en los mensajes recientes de #canal'\n"
    "    o 'no tengo ese dato cargado ahora'. NUNCA niegues acceso al servidor.\n"
    "11) PROHIBIDO INVENTAR REQUISITOS. Si te preguntan 'como ser mod/staff/tryouter/voucher/manager', 'que requisitos hay para X rol',\n"
    "    'como me hago voucher', etc., y NO tenes la info oficial en [LIVE DATA - ...] ni en este prompt, DICE TEXTUAL:\n"
    "    'No tengo los requisitos oficiales cargados. Preguntale a un staff o revisa #role-guide'.\n"
    "    JAMAS improvises una lista generica como 'ser activo, buen comportamiento, tener skill, ser recomendado'. Eso es inventar.\n"
    "12) Si hay [LIVE DATA - Server roles] y el usuario pregunta por un rol, BUSCA en esa lista el rol exacto. Si no aparece,\n"
    "    decile que no existe ese rol en el servidor (en vez de adivinar o inventar requisitos).\n"
    "13) REGISTRY DE USUARIOS: el bot mantiene un registro persistente de TODOS los miembros del servidor\n"
    "    (username, display_name, roles, joined_at, last_seen, streak). Cada vez que el usuario pregunte por\n"
    "    un miembro especifico, revisa [LIVE DATA - Mentioned users] y [LIVE DATA - Server registry].\n"
    "    El registry vive en user_registry.json y se actualiza en cada mensaje y activity check.\n"
    "14) PROHIBIDO decir 'no tengo informacion sobre ese usuario' / 'no encuentro a ese miembro' /\n"
    "    'no conozco a ese user' si el usuario aparece en [LIVE DATA - Mentioned users] o en el registry.\n"
    "    Si te mencionan a alguien y esta en el registry, tenes su info completa: usala. Si explicitamente\n"
    "    figura como 'NO esta en el registry', recien ahi deci 'ese usuario no esta en el registro del clan'.\n"
    "15) PROHIBIDO INVENTAR CANALES. Solo podes mencionar canales que aparecen en [LIVE DATA - Server channels]\n"
    "    o en los datos del servidor (SYSTEM_PROMPT de abajo). NUNCA inventes nombres tipo '#reglas-del-clan',\n"
    "    '#canal-de-staff', etc., solo porque suena logico. Si el canal no existe, deci 'no encontre ese canal,\n"
    "    aca no tenemos un canal asi'.\n"
    "16) TONO SERIO Y DIRECTO. Nada de 'Claro!', 'Por supuesto!', 'No te preocupes!', ni emojis innecesarios,\n"
    "    ni disclaimers tipo 'espero haberte ayudado'. Respondes al grano. Una oracion siempre que sea posible.\n"
    "17) IDENTIDAD DEL SERVIDOR: cuando te pregunten 'en que servidor estas', 'que clan es este', 'como se llama el server',\n"
    "    revisa [LIVE DATA - Server registry] y contesta con el nombre real del guild (normalmente 'Celestials Dragons').\n"
    "    NO digas que no sabes en que server estas. El campo 'guild' del registry es tu fuente.\n"
    "=========\n"
)

LANG_DIRECTIVES = {
    "en": (
        "LANGUAGE LOCK: The user's latest message is in ENGLISH. "
        "You MUST reply in English ONLY. Do not switch to Spanish or Portuguese under any circumstances."
    ),
    "pt": (
        "LANGUAGE LOCK: A mensagem mais recente do usuario esta em PORTUGUES. "
        "Voce DEVE responder APENAS em portugues. Nao mude para espanhol ou ingles."
    ),
    "es": (
        "LANGUAGE LOCK: El ultimo mensaje del usuario esta en ESPANOL. "
        "DEBES responder SOLO en espanol. No cambies a ingles ni portugues."
    ),
}

_PT_MARKERS = [
    " voce ", "voce,", "você", " voces ", "obrigad", "não ", " nao ", " está", " estão",
    " olá", " oi ", " sim ", " aqui ", "jogador", "jogadores", " clã",
    " comigo", " fazía", " será ", " ninguém", " alguém", " também",
    " muito ", " onde ", " porque ", " porquê", " quem ", " entao ", " então ",
    " qual ", " quais ", " acha ", " achou ", " é ", " são ", " está ",
    " meu ", " minha ", " seu ", " sua ", " nosso ", " nossa ", " deles ",
    " obrigado", " isso ", " isto ", " tudo ", " nada ", " agora ",
    " ontem ", " hoje ", " amanha ", " amanhã ", " fazer ", " faz ",
]
_EN_MARKERS = [
    " the ", " and ", " is ", " are ", " what ", " how ", " why ", " when ",
    " where ", " who ", " you ", " your ", " can ", " could ", " would ",
    " please ", " of ", " does ", " do you", " did ", " say ", " this ",
    " that ", " these ", " tell me ", " i am ", " i'm ", " who is ", " what's ",
]
_ES_MARKERS = [
    "¿", "¡", " qué ", " quién", " cómo ", " que ", " eres ", " soy ",
    " está ", " tú ", " usted ", " algún ", " lo que ", " por qué ",
    " cuál ", " cuando ", " donde ", " hola ", " qué", " cómo", " sí ",
    " pero ", " también ", " así ", " siempre ", " nunca ", " decime",
]


def detect_language(text: str) -> str:
    """Return 'en', 'pt', or 'es' based on simple marker heuristics."""
    t = f" {(text or '').lower()} "
    pt = sum(1 for m in _PT_MARKERS if m in t)
    en = sum(1 for m in _EN_MARKERS if m in t)
    es = sum(1 for m in _ES_MARKERS if m in t)
    # Strong PT: words that almost never appear in ES
    if any(strong in t for strong in ["você", "não", " obrigad", " clã", " também", "jogador"]):
        pt += 3
    # Strong EN: question words in English
    if any(strong in t for strong in [" what is ", " who is ", " how do ", " what does ", " can you "]):
        en += 3
    if pt > es and pt > en:
        return "pt"
    if en > es and en > pt:
        return "en"
    if es > 0 or pt == en == 0:
        return "es"
    return "es"


_CHANNEL_TOPIC_HINTS: dict[str, list[str]] = {
    "mod": ["role-guide", "rules"],
    "staff": ["role-guide", "rules"],
    "moderator": ["role-guide", "rules"],
    "moderador": ["role-guide", "rules"],
    "tryouter": ["role-guide", "tryout-info"],
    "como ser": ["role-guide"],
    "how to be": ["role-guide"],
    "how do i become": ["role-guide"],
    "how can i become": ["role-guide"],
    "requisito": ["role-guide", "rules"],
    "requirement": ["role-guide", "rules"],
    "roles": ["role-guide"],
    "role guide": ["role-guide"],
    "role-guide": ["role-guide"],
    "overview": ["overview"],
    "welcome": ["welcome"],
    "top 10": ["top-10"],
    "top-10": ["top-10"],
    "top 20": ["top-20"],
    "top-20": ["top-20"],
    "top 30": ["top-30"],
    "top-30": ["top-30"],
    "leaderboard": ["top-10", "top-20", "top-30"],
    "phase record": ["phase-record"],
    "phase-record": ["phase-record"],
    "sae": ["phase-record-sae", "sae-annc", "sae-anncs"],
    "saw": ["phase-record-saw", "saw-annc", "saw-anncs"],
    "rules": ["rules"],
    "reglas": ["rules"],
    "punishment": ["punishments"],
    "punishments": ["punishments"],
    "sanction": ["punishments"],
    "sanciones": ["punishments"],
    "blacklist": ["blacklist"],
    "unblacklist": ["unblacklist"],
    "annc": ["server-annc", "server-anncs"],
    "anncs": ["server-annc", "server-anncs"],
    "announcement": ["server-annc", "server-anncs"],
    "anuncio": ["server-annc", "server-anncs"],
    "anuncios": ["server-annc", "server-anncs"],
    "tryout result": ["tryout-results"],
    "tryout-results": ["tryout-results"],
    "training result": ["training-results"],
    "training-results": ["training-results"],
    "p1 low trial": ["p1-low-trial-result"],
    "p1 mid trial": ["p1-mid-trial-result"],
    "set score": ["set-scores"],
    "set-scores": ["set-scores"],
    "challenge": ["challenge-ticket"],
    "hall of fame": ["hall-of-fame"],
    "hall of shame": ["hall-of-shame"],
    "suggestions": ["suggestions"],
    "sugerencias": ["suggestions"],
    "events": ["events"],
    "eventos": ["events"],
    "memes": ["memes"],
    "media": ["media"],
    "overview": ["overview"],
    "role guide": ["role-guide"],
    "role-guide": ["role-guide"],
    "tryout info": ["tryout-info"],
    "training info": ["training-info"],
}


async def find_text_channel_by_name(name_query: str) -> "discord.TextChannel | None":
    guild = client.get_guild(GUILD_ID)
    if not guild:
        return None
    target = name_query.lower().strip().replace(" ", "-").lstrip("#")
    # exact match first
    for ch in guild.text_channels:
        if ch.name.lower() == target:
            return ch
    # substring match (longest)
    best = None
    best_len = 0
    for ch in guild.text_channels:
        cname = ch.name.lower()
        if target in cname and len(cname) > best_len:
            best = ch
            best_len = len(cname)
    return best


_TSB_KEYWORDS = re.compile(
    r"\b(tsb|tsbl|tsbcc|phase|phases|tier|tiers|glad|glads|gladiador|"
    r"tryout|tryouts|trial|trials|vouch|vouchs|clan|clans|server|servidor|"
    r"celestial|celestials|dragon|dragons|friity|saitama|garou|metal bat|"
    r"leaderboard|top ?10|top ?20|top ?30|boomy|ayato|competitive|competitivo|"
    r"warn|warns|blacklist|ban|sancion|sanción|sancoes|"
    r"owner|owners|staff|tryouter|moderator|moderador|skill lookout|"
    r"voucher|applicant|regla|reglas|rule|rules|sanction|sanciones|"
    r"punishment|punishments|hunter|lordheaven|aba|tab glitch|"
    r"bullet dash|passive strike|sneaking|1v1|ft3|ft5|ft10|"
    r"activity check|streak|streaks|polls?|encuesta|anncs?|anuncios?|"
    r"roblox|discord|canal|channel|miembro|miembros|member|members|"
    r"jugador|jugadores|player|players|rol|roles|role|sid|ffrsid|bot)\b",
    re.IGNORECASE,
)


async def fetch_recent_channel_messages(
    channel: discord.abc.Messageable,
    limit: int = 80,
    target_user_id: int | None = None,
    target_name: str | None = None,
    exclude_message_id: int | None = None,
) -> list[dict]:
    results: list[dict] = []
    try:
        async for msg in channel.history(limit=limit):
            if exclude_message_id and msg.id == exclude_message_id:
                continue
            if msg.author.bot:
                continue
            if not msg.content:
                continue
            if msg.content.startswith(">") or msg.content.lower().startswith("?activity"):
                continue
            results.append({
                "author_id": msg.author.id,
                "author": getattr(msg.author, "display_name", None) or msg.author.name,
                "username": msg.author.name,
                "content": msg.content,
                "created_at": msg.created_at.isoformat(timespec="seconds"),
            })
    except Exception as e:
        print(f"[ask] channel history fetch failed: {e}")
        return []
    results.reverse()

    if target_user_id is not None:
        results = [m for m in results if m["author_id"] == target_user_id]
    elif target_name:
        lname = target_name.lower().lstrip("@").strip()
        results = [
            m for m in results
            if lname in m["author"].lower() or lname in m["username"].lower()
        ]

    return results


_WEB_HTML_TAG_RE = re.compile(r"<[^>]+>")
_WEB_WS_RE = re.compile(r"\s+")
_WEB_RESULT_RE = re.compile(
    r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>'
    r'.*?<a[^>]+class="result__snippet"[^>]*>(.*?)</a>',
    re.DOTALL | re.IGNORECASE,
)


def _strip_html(text: str) -> str:
    import html as _html
    text = _WEB_HTML_TAG_RE.sub("", text)
    text = _html.unescape(text)
    text = _WEB_WS_RE.sub(" ", text).strip()
    return text


async def web_search(query: str, max_results: int = 5) -> list[dict]:
    query = (query or "").strip()
    if not query:
        return []

    results: list[dict] = []

    try:
        async with aiohttp.ClientSession() as session:
            params = {"q": query, "format": "json", "no_html": "1", "skip_disambig": "1"}
            async with session.get(
                "https://api.duckduckgo.com/",
                params=params,
                timeout=aiohttp.ClientTimeout(total=8),
            ) as resp:
                if resp.status == 200:
                    data = await resp.json(content_type=None)
                    abstract = (data.get("AbstractText") or "").strip()
                    heading = (data.get("Heading") or "").strip()
                    abstract_url = data.get("AbstractURL") or ""
                    if abstract:
                        results.append({
                            "title": heading or query,
                            "url": abstract_url,
                            "snippet": abstract,
                        })
                    for related in (data.get("RelatedTopics") or []):
                        if len(results) >= max_results:
                            break
                        if isinstance(related, dict):
                            text = (related.get("Text") or "").strip()
                            if text:
                                results.append({
                                    "title": text[:120],
                                    "url": related.get("FirstURL", ""),
                                    "snippet": text,
                                })
    except Exception as e:
        print(f"[web_search] instant answer failed: {e}")

    if len(results) < max_results:
        try:
            headers = {
                "User-Agent": (
                    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
                )
            }
            async with aiohttp.ClientSession(headers=headers) as session:
                async with session.get(
                    "https://html.duckduckgo.com/html/",
                    params={"q": query},
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status == 200:
                        html_text = await resp.text()
                        for match in _WEB_RESULT_RE.finditer(html_text):
                            url = match.group(1)
                            title = _strip_html(match.group(2))
                            snippet = _strip_html(match.group(3))
                            if url.startswith("//duckduckgo.com/l/?uddg=") or "duckduckgo.com/l/?uddg=" in url:
                                from urllib.parse import unquote, parse_qs, urlparse
                                parsed = urlparse(url if url.startswith("http") else "https:" + url)
                                qs = parse_qs(parsed.query)
                                if "uddg" in qs:
                                    url = unquote(qs["uddg"][0])
                            if title and snippet:
                                results.append({"title": title, "url": url, "snippet": snippet})
                            if len(results) >= max_results:
                                break
        except Exception as e:
            print(f"[web_search] html search failed: {e}")

    seen_urls = set()
    deduped: list[dict] = []
    for r in results:
        key = r.get("url") or r.get("snippet")
        if key in seen_urls:
            continue
        seen_urls.add(key)
        deduped.append(r)
    return deduped[:max_results]


async def get_guild_members(role_id: int | None = None) -> list[dict]:
    headers = {"Authorization": f"Bot {DISCORD_BOT_TOKEN}"}
    members: list[dict] = []
    after = 0
    async with aiohttp.ClientSession() as session:
        while True:
            params = {"limit": 1000, "after": after}
            async with session.get(
                f"{DISCORD_API_BASE}/guilds/{GUILD_ID}/members",
                headers=headers,
                params=params,
            ) as resp:
                if resp.status != 200:
                    break
                batch = await resp.json()
                if not batch:
                    break
                for m in batch:
                    if role_id is None or str(role_id) in [str(r) for r in m.get("roles", [])]:
                        nick = m.get("nick") or (m.get("user") or {}).get("global_name") or (m.get("user") or {}).get("username", "Unknown")
                        members.append({"name": nick, "roles": m.get("roles", [])})
                if len(batch) < 1000:
                    break
                after = int(batch[-1]["user"]["id"])
    return members


async def get_guild_roles() -> list[dict]:
    headers = {"Authorization": f"Bot {DISCORD_BOT_TOKEN}"}
    async with aiohttp.ClientSession() as session:
        async with session.get(
            f"{DISCORD_API_BASE}/guilds/{GUILD_ID}/roles",
            headers=headers,
        ) as resp:
            if resp.status != 200:
                return []
            roles = await resp.json()
            return [{"id": r["id"], "name": r["name"]} for r in roles if not r.get("managed")]


async def get_guild_channels() -> list[dict]:
    headers = {"Authorization": f"Bot {DISCORD_BOT_TOKEN}"}
    async with aiohttp.ClientSession() as session:
        async with session.get(
            f"{DISCORD_API_BASE}/guilds/{GUILD_ID}/channels",
            headers=headers,
        ) as resp:
            if resp.status != 200:
                return []
            channels = await resp.json()
            type_names = {0: "text", 2: "voice", 4: "category", 5: "announcement", 15: "forum"}
            return [
                {"name": c["name"], "type": type_names.get(c["type"], "other")}
                for c in channels
                if c["type"] != 4
            ]


def _build_live_context(
    question: str,
    members: list[dict] | None,
    roles: list[dict] | None,
    channels: list[dict] | None,
    author_info: dict | None = None,
    channel_messages: list[dict] | None = None,
    web_results: list[dict] | None = None,
    detected_role_name: str | None = None,
    cross_channel_messages: dict[str, list[dict]] | None = None,
    guild_id: int | None = None,
    mentioned_user_ids: list[int] | None = None,
) -> str | None:
    parts: list[str] = []

    # [LIVE DATA - Server registry] siempre que haya guild_id
    if guild_id is not None:
        gentry = _user_registry.get(str(guild_id))
        if gentry:
            users = gentry.get("users") or {}
            total = len(users)
            humans = sum(1 for u in users.values() if not u.get("is_bot"))
            bots = total - humans
            parts.append(
                "[LIVE DATA — Server registry]: "
                f"guild='{gentry.get('name', '?')}' (id {guild_id}), "
                f"registered_users={total} (humans {humans}, bots {bots}), "
                f"last_snapshot={gentry.get('updated_at') or '?'}. "
                "Tenes el registro completo de users del server en memoria. "
                "Si te preguntan por 'usuarios', 'miembros', 'quienes son', etc., USAS ESTO, "
                "nunca digas que no tenes info del server."
            )

    # [LIVE DATA - Mentioned users]: entradas del registry de cada @mencion
    if mentioned_user_ids:
        user_lines: list[str] = []
        for uid in mentioned_user_ids:
            formatted = format_user_registry_entry(uid, guild_id)
            if formatted:
                user_lines.append(f"- {formatted}")
            else:
                user_lines.append(f"- id={uid}: NO esta en el registry (usuario desconocido)")
        if user_lines:
            parts.append(
                "[LIVE DATA — Mentioned users]:\n"
                + "\n".join(user_lines)
                + "\nEsta es la data OFICIAL de los usuarios mencionados en el mensaje. "
                "USASELA para responder preguntas sobre ellos. NO digas 'no tengo info de este usuario'."
            )

    if author_info:
        roles_text = ", ".join(author_info.get("roles") or []) or "sin roles destacados"
        parts.append(
            "[WHO IS ASKING — data from Discord]: "
            f"display_name={author_info['display_name']}, "
            f"username={author_info['username']}, "
            f"id={author_info['id']}, "
            f"roles=[{roles_text}]. "
            "Cuando el usuario pregunte 'quien soy', 'who am I', 'quien es este', etc., "
            "respondé usando el display_name y/o los roles que aparecen acá. "
            "No inventes datos ni confundas al usuario con otro. Usa estos valores EXACTOS."
        )

    if members is not None:
        header = "[LIVE DATA — Server members"
        if detected_role_name:
            header += f" filtrados por rol '{detected_role_name}'"
        if len(members) == 0:
            parts.append(
                f"{header}]: 0 miembros coinciden con este filtro. "
                "NO inventes nombres ni numeros. El conteo real es 0."
            )
        else:
            names = [m["name"] for m in members]
            parts.append(
                f"{header} — EXACT COUNT FROM API: {len(names)}]: "
                f"{', '.join(names)}. "
                "Use this exact count and these exact names. Do NOT add, remove, or guess any members."
            )

    if roles:
        role_names = [r["name"] for r in roles]
        parts.append(f"[LIVE DATA — Server roles — fetched live from API]: {', '.join(role_names)}")

    if channels:
        ch_list = [f"#{c['name']} ({c['type']})" for c in channels]
        parts.append(f"[LIVE DATA — Server channels — fetched live from API]: {', '.join(ch_list)}")

    if channel_messages:
        recent = channel_messages[-40:]
        lines = [
            f"- [{m['created_at']}] {m['author']} (@{m['username']}): {m['content']}"
            for m in recent
        ]
        parts.append(
            "[LIVE DATA — Mensajes recientes del canal actual, en orden cronologico (mas viejo primero)]:\n"
            + "\n".join(lines)
            + "\nUsa SOLO estos mensajes para responder 'que dijo X' o preguntas sobre el chat. "
            "Si el usuario mencionado no aparece aca, decile que no lo encontraste en los mensajes recientes. "
            "No inventes ni parafrasees; cita tal cual."
        )

    if cross_channel_messages:
        blocks: list[str] = []
        for ch_name, msgs in cross_channel_messages.items():
            recent = msgs[-25:]
            ch_lines = [
                f"  - [{m['created_at']}] {m['author']} (@{m['username']}): {m['content']}"
                for m in recent
            ]
            blocks.append(f"CANAL {ch_name} (mas viejo primero):\n" + "\n".join(ch_lines))
        parts.append(
            "[LIVE DATA — Mensajes de otros canales relevantes del servidor]:\n"
            + "\n\n".join(blocks)
            + "\nUsa SOLO estos mensajes como fuente de verdad para preguntas sobre top 10, rules, "
            "anncs, phase-record, blacklist, tryout-results, etc. NO inventes datos que no esten acá. "
            "Si la respuesta no está en estos mensajes, decí que no lo encontraste en el canal "
            "y sugeri al usuario que revise ese canal directamente."
        )

    if web_results:
        lines = []
        for r in web_results[:5]:
            title = r.get("title") or ""
            snippet = r.get("snippet") or ""
            url = r.get("url") or ""
            lines.append(f"- {title}\n  {snippet}\n  fuente: {url}")
        parts.append(
            "[LIVE DATA — Resultados de busqueda web (DuckDuckGo)]:\n"
            + "\n".join(lines)
            + "\nUsa esta info para responder preguntas generales que NO sean del clan/servidor/TSB. "
            "Resume en el idioma del usuario. Si mencionas un dato especifico, cita brevemente la fuente (URL). "
            "Si los resultados no contestan la pregunta, decilo honestamente."
        )

    if not parts:
        return None
    return "\n\n".join(parts)


async def handle_ask(message: discord.Message):
    question = message.content[len(">ask"):].strip()

    reply_target: discord.Member | discord.User | None = None
    if message.mentions:
        reply_target = message.mentions[0]
        for pattern in (f"<@!{reply_target.id}>", f"<@{reply_target.id}>"):
            question = question.replace(pattern, "")
        question = question.strip()

    if not question:
        await message.channel.send("Please provide a question after `>ask`.")
        return

    user_id = message.author.id
    history = conversation_history[user_id]

    history.append({"role": "user", "content": question})

    if len(history) > MAX_HISTORY_MESSAGES:
        history = history[-MAX_HISTORY_MESSAGES:]
        conversation_history[user_id] = history

    author_info = {
        "id": message.author.id,
        "username": message.author.name,
        "display_name": getattr(message.author, "display_name", None) or message.author.name,
        "roles": [
            r.name
            for r in getattr(message.author, "roles", [])
            if r.name and r.name != "@everyone"
        ],
    }

    wants_members = bool(_MEMBER_KEYWORDS.search(question))
    wants_roles = bool(_ROLE_KEYWORDS.search(question))
    wants_channels = bool(_CHANNEL_KEYWORDS.search(question))
    wants_channel_history = bool(_CHANNEL_HISTORY_KEYWORDS.search(question)) or bool(reply_target)
    wants_web = bool(_WEB_SEARCH_KEYWORDS.search(question))
    asks_about_staff = bool(_STAFF_KEYWORDS.search(question))
    user_lang = detect_language(question)

    # Para preguntas del clan (no TSBL-only), siempre traemos roles y channels
    # porque son baratos (una API call cada uno) y evitan que el bot diga
    # "no tengo acceso" o invente info.
    is_tsbl_only_question = bool(_TSB_KEYWORDS.search(question)) and not (
        wants_members or wants_roles or wants_channels
        or wants_channel_history or asks_about_staff
    )
    if not is_tsbl_only_question:
        wants_roles = True
        wants_channels = True
    if asks_about_staff:
        # Las preguntas de 'como ser mod/staff' requieren ver miembros y roles
        wants_members = True

    live_members: list[dict] | None = None
    live_roles: list[dict] | None = None
    live_channels: list[dict] | None = None
    channel_messages: list[dict] | None = None
    web_results: list[dict] | None = None
    detected_role_name: str | None = None
    cross_channel_messages: dict[str, list[dict]] = {}

    answer = None
    # Mensaje de "Buscando..." que editamos al final con la respuesta real.
    searching_text = {
        "en": "Searching…",
        "pt": "Buscando…",
        "es": "Buscando…",
    }.get(user_lang, "Buscando…")
    status_message: discord.Message | None = None
    try:
        status_message = await message.channel.send(searching_text)
    except Exception as e:
        print(f"[ask] could not send status message: {e}")

    async with message.channel.typing():
        # -------- Contexto: mensajes recientes del canal --------
        if wants_channel_history:
            try:
                target_user_id = reply_target.id if reply_target else None
                target_name: str | None = None
                if target_user_id is None:
                    name_match = re.search(
                        r"(?:que (?:dijo|escribio|escribió|puso|coment(?:o|ó))|what did)\s+@?([\w\-_.áéíóúñÁÉÍÓÚÑ]+)",
                        question,
                        re.IGNORECASE,
                    )
                    if name_match:
                        target_name = name_match.group(1).strip()
                channel_messages = await fetch_recent_channel_messages(
                    message.channel,
                    limit=80,
                    target_user_id=target_user_id,
                    target_name=target_name,
                    exclude_message_id=message.id,
                )
                print(
                    f"[ask] channel history: target_id={target_user_id} "
                    f"target_name={target_name} got {len(channel_messages)} msgs"
                )
            except Exception as e:
                print(f"[ask] channel history error: {e}")

        # -------- Contexto: mensajes de otros canales (mencionados o por tema) --------
        try:
            mentioned_channels = []
            for ch in getattr(message, "channel_mentions", []) or []:
                if ch.id != message.channel.id and isinstance(ch, discord.TextChannel):
                    mentioned_channels.append(ch)

            for ch in mentioned_channels[:3]:
                msgs = await fetch_recent_channel_messages(
                    ch, limit=40, exclude_message_id=message.id
                )
                if msgs:
                    cross_channel_messages[f"#{ch.name}"] = msgs

            if not mentioned_channels:
                lowered = question.lower()
                matched_names: list[str] = []
                for keyword, chan_names in _CHANNEL_TOPIC_HINTS.items():
                    if keyword in lowered:
                        for cn in chan_names:
                            if cn not in matched_names:
                                matched_names.append(cn)
                for chan_name in matched_names[:3]:
                    if f"#{chan_name}" in cross_channel_messages:
                        continue
                    ch = await find_text_channel_by_name(chan_name)
                    if ch and ch.id != message.channel.id:
                        msgs = await fetch_recent_channel_messages(
                            ch, limit=40, exclude_message_id=message.id
                        )
                        if msgs:
                            cross_channel_messages[f"#{ch.name}"] = msgs
            if cross_channel_messages:
                print(
                    f"[ask] cross-channel msgs: "
                    f"{ {k: len(v) for k, v in cross_channel_messages.items()} }"
                )
        except Exception as e:
            print(f"[ask] cross-channel fetch error: {e}")

        # -------- Contexto: miembros/roles/canales del server --------
        if wants_members or wants_roles or wants_channels:
            print(
                f"[ask] Live data fetch triggered — "
                f"members={wants_members} roles={wants_roles} channels={wants_channels}"
            )
            try:
                raw_roles = await get_guild_roles()
                if wants_roles:
                    live_roles = raw_roles

                if wants_members:
                    role_filter_id: int | None = None
                    role_match = _ROLE_FILTER_RE.search(question)
                    if role_match:
                        role_name_query = role_match.group(1).strip().lower()
                        matched_role = next(
                            (r for r in raw_roles if role_name_query in r["name"].lower()),
                            None,
                        )
                        if matched_role:
                            role_filter_id = int(matched_role["id"])
                            detected_role_name = matched_role["name"]
                    else:
                        q_lower = question.lower()
                        best_match = None
                        best_match_len = 0
                        for r in raw_roles:
                            rname = (r["name"] or "").lower().strip()
                            if len(rname) < 3:
                                continue
                            if rname in q_lower and len(rname) > best_match_len:
                                best_match = r
                                best_match_len = len(rname)
                        if best_match:
                            role_filter_id = int(best_match["id"])
                            detected_role_name = best_match["name"]

                    live_members = await get_guild_members(role_id=role_filter_id)

                if wants_channels:
                    live_channels = await get_guild_channels()
            except Exception as e:
                print(f"[ask] Live data fetch error: {e}")

        # -------- Contexto: busqueda web --------
        if wants_web:
            try:
                web_results = await web_search(question, max_results=5)
                print(f"[ask] web search returned {len(web_results)} results")
            except Exception as e:
                print(f"[ask] web search error: {e}")

        mentioned_ids = [u.id for u in (message.mentions or []) if not getattr(u, "bot", False) or True]
        # Si el author menciono a alguien, nos aseguramos de tenerlo fresco en el registry
        if message.guild is not None:
            for mu in (message.mentions or []):
                try:
                    update_user_in_registry(mu, message.guild, bump_last_seen=False)
                except Exception:
                    pass

        # Resolucion fuzzy de usuarios por nombre (sin @). Agrega al registry matches encontrados.
        if message.guild is not None:
            fuzzy_matches = _resolve_users_by_name(question, message.guild.id, limit=5)
            for fuid in fuzzy_matches:
                if fuid not in mentioned_ids:
                    mentioned_ids.append(fuid)
            if fuzzy_matches:
                print(f"[ask] fuzzy user matches: {fuzzy_matches}")

        live_context = _build_live_context(
            question,
            live_members,
            live_roles,
            live_channels,
            author_info=author_info,
            channel_messages=channel_messages,
            web_results=web_results,
            detected_role_name=detected_role_name,
            cross_channel_messages=cross_channel_messages or None,
            guild_id=(message.guild.id if message.guild is not None else None),
            mentioned_user_ids=mentioned_ids or None,
        )

        lang_directive = LANG_DIRECTIVES.get(user_lang, LANG_DIRECTIVES["es"])
        system_with_context = lang_directive + CRITICAL_RULES + "\n\n" + SYSTEM_PROMPT
        if live_context:
            system_with_context += (
                "\n\n--- REAL-TIME SERVER DATA (use this to answer accurately) ---\n"
                + live_context
            )

        current_history = list(history)

        for cycle in range(_ASK_MAX_CYCLES):
            if cycle > 0:
                print(f"[ask] All models rate-limited — waiting {_ASK_CYCLE_DELAY}s before cycle {cycle + 1}/{_ASK_MAX_CYCLES}...")
                await asyncio.sleep(_ASK_CYCLE_DELAY)

            all_rate_limited = True

            for model in FALLBACK_MODELS:
                try:
                    print(f"[ask] Trying model: {model}")
                    messages_payload = [
                        {"role": "system", "content": system_with_context},
                        *current_history,
                    ]
                    response = await groq_client.chat.completions.create(
                        model=model,
                        messages=messages_payload,
                    )
                    answer = response.choices[0].message.content
                    all_rate_limited = False
                    break

                except Exception as e:
                    status = getattr(e, "status_code", None)

                    if status == 413:
                        all_rate_limited = False
                        print(f"[ask] {model} → 413 (too large), trimming history...")
                        if len(current_history) > 2:
                            current_history = current_history[-(len(current_history) // 2):]
                            try:
                                messages_payload = [
                                    {"role": "system", "content": system_with_context},
                                    *current_history,
                                ]
                                response = await groq_client.chat.completions.create(
                                    model=model,
                                    messages=messages_payload,
                                )
                                answer = response.choices[0].message.content
                                break
                            except Exception:
                                pass
                        continue

                    elif status == 429:
                        print(f"[ask] {model} → 429 (rate limit), waiting {_ASK_MODEL_429_DELAY}s then trying next model...")
                        await asyncio.sleep(_ASK_MODEL_429_DELAY)
                        continue

                    else:
                        all_rate_limited = False
                        print(f"[ask] {model} failed: {e}")
                        continue

            if answer is not None or not all_rate_limited:
                break

    if answer is None:
        overload_msg = "⚠️ The bot is temporarily overloaded. Please try again in a few minutes."
        if status_message is not None:
            try:
                await status_message.edit(content=overload_msg)
            except Exception:
                await message.channel.send(overload_msg)
        else:
            await message.channel.send(overload_msg)
        history.pop()
        return

    history.append({"role": "assistant", "content": answer})

    if len(history) > MAX_HISTORY_MESSAGES:
        conversation_history[user_id] = history[-MAX_HISTORY_MESSAGES:]

    prefix = f"<@{reply_target.id}> " if reply_target else ""
    full_text = prefix + answer

    if len(full_text) > 2000:
        # La respuesta es muy larga: borra el status y manda los chunks.
        if status_message is not None:
            try:
                await status_message.delete()
            except Exception:
                pass
        first = True
        remaining = answer
        while remaining:
            budget = 2000 - (len(prefix) if first else 0)
            chunk = remaining[:budget]
            remaining = remaining[budget:]
            await message.channel.send((prefix if first else "") + chunk)
            first = False
    else:
        # Edita el mensaje de "Buscando..." con la respuesta real.
        if status_message is not None:
            try:
                await status_message.edit(content=full_text)
            except Exception:
                await message.channel.send(full_text)
        else:
            await message.channel.send(full_text)


_POLL_TIME_UNITS: dict[str, int] = {
    "second": 1,
    "minute": 60,
    "hour": 3600,
    "day": 86400,
    "week": 604800,
    "month": 2592000,
    "year": 31536000,
}


async def handle_poll(message: discord.Message):
    if message.channel.id != POLL_CHANNEL_ID:
        try:
            await message.delete()
        except Exception:
            pass
        await message.channel.send(
            "Polls can only be created in the designated poll channel.", delete_after=5
        )
        return

    author_role_ids = {r.id for r in message.author.roles}
    if POLL_ROLE_ID not in author_role_ids:
        await message.channel.send(
            "You don't have permission to use this command.", delete_after=5
        )
        return

    raw = message.content[len(">poll"):].strip()

    vote_match = re.search(r"\bvote:\s*(\d+)", raw, re.IGNORECASE)
    time_match = re.search(
        r"\btime:\s*(\d+)\s*(second|minute|hour|day|week|month|year)s?",
        raw, re.IGNORECASE,
    )

    if vote_match and time_match:
        await message.channel.send(
            "Use either `vote:` or `time:`, not both.", delete_after=5
        )
        return

    if not vote_match and not time_match:
        await message.channel.send(
            "You must specify `vote: <number>` or `time: <number> <second/minute/hour/day/week/month/year>`.",
            delete_after=5,
        )
        return

    vote_goal: int | None = None
    time_seconds: float | None = None

    if vote_match:
        vote_goal = int(vote_match.group(1))
        raw = (raw[: vote_match.start()] + raw[vote_match.end() :]).strip()

    if time_match:
        n = int(time_match.group(1))
        unit = time_match.group(2).lower()
        time_seconds = float(n * _POLL_TIME_UNITS[unit])
        raw = (raw[: time_match.start()] + raw[time_match.end() :]).strip()

    parts = [p.strip() for p in raw.split("|")]
    if len(parts) < 3:
        await message.channel.send(
            "You need a question and at least 2 options separated by `|`.",
            delete_after=5,
        )
        return
    if len(parts) > 5:
        await message.channel.send("Maximum 4 options allowed.", delete_after=5)
        return

    question = parts[0]
    options = parts[1:]

    try:
        await message.delete()
    except Exception:
        pass

    poll_id = str(uuid.uuid4())[:8]
    close_at = (
        datetime.now(timezone.utc).timestamp() + time_seconds if time_seconds else None
    )
    state = PollState(
        poll_id=poll_id,
        question=question,
        options=options,
        vote_goal=vote_goal,
        close_at=close_at,
        channel_id=message.channel.id,
        accent_color=random.choice(_POLL_ACCENT_COLORS),
    )

    data = await _discord_api_request(
        "POST",
        f"/channels/{message.channel.id}/messages",
        {"flags": COMPONENTS_V2_FLAG, "components": build_poll_components(state)},
    )
    state.message_id = data.get("id")
    active_polls[poll_id] = state

    notif_channel = message.guild.get_channel(POLL_NOTIFICATION_CHANNEL_ID)
    if notif_channel:
        notif_msg = await notif_channel.send(f"New poll created: **{question}**")
        asyncio.create_task(_delete_after(notif_msg, 3))

    if time_seconds:
        asyncio.create_task(_auto_close_poll(poll_id, time_seconds))


SETUPRULES_CHANNEL_ID = 1451654847408373944


async def handle_setuprules(message: discord.Message):
    if message.channel.id != SETUPRULES_CHANNEL_ID:
        await message.channel.send("Este comando solo puede usarse en el canal de rules.")
        return

    embed1 = discord.Embed()
    embed1.set_image(url="https://cdn.discordapp.com/attachments/1451654847408373947/1489704763585986650/1775238806516.png")

    embed2 = discord.Embed(
        title="Celestials Dragons | Rules",
        description=(
            "Welcome to Celestials Dragons! Please select your language to read the clan rules.\n\n"
            "[Discord Terms of Service](https://discord.com/terms)"
        ),
        color=0xFF69B4,
    )

    await message.channel.send(embeds=[embed1, embed2], view=RulesView())


RULESV2_CHANNEL_OPTIONS: list[int] = [
    1487884455728124014,
    1487268275963428895,
    1487268312244289537,
    1451396134105911427,
]

# Imagen principal del container de >rulesv2 (sustituye a RULES_IMAGE_URL aca)
RULESV2_IMAGE_URL: str = (
    "https://cdn.discordapp.com/attachments/1451654847408373947/"
    "1495469836598378576/1776618183605.jpg?ex=69e65c51&is=69e50ad1"
    "&hm=14c5c1d91869244791d91344d5df13cd447b30d48646850732871284e1e88c97&"
)

# Emoji a mostrar antes del titulo (reemplaza al punto medio ・)
RULESV2_TITLE_EMOJI: str = "<:emoji_57:1495457372691365899>"


async def handle_rulesv2(message: discord.Message):
    """Postea el container Components V2 con dropdown de canales.

    Solo el owner puede correrlo y solo en SETUPRULES_CHANNEL_ID.
    El dropdown usa StringSelect con IDs reales de canales; al seleccionar,
    el bot responde efímero con <#channel_id> (mencion clickeable para saltar).
    """
    if message.channel.id != SETUPRULES_CHANNEL_ID:
        await message.channel.send("Este comando solo puede usarse en el canal de rules.")
        return
    if BOT_OWNER_ID is not None and message.author.id != BOT_OWNER_ID:
        await message.channel.send("Solo el owner puede usar este comando.")
        return

    guild = message.guild
    options: list[dict] = []
    for cid in RULESV2_CHANNEL_OPTIONS:
        ch = guild.get_channel(cid) if guild else None
        label = (ch.name if ch else f"channel-{cid}")[:100]
        desc = (f"Ir a #{ch.name}"[:100]) if ch else "Canal no encontrado"
        options.append({
            "label": label,
            "value": str(cid),
            "description": desc,
        })

    payload = {
        "flags": COMPONENTS_V2_FLAG,
        "components": [
            {
                "type": 17,
                "components": [
                    {
                        "type": 12,
                        "items": [{"media": {"url": RULESV2_IMAGE_URL}}],
                    },
                    {"type": 14, "spacing": 2},
                    {
                        "type": 10,
                        "content": (
                            f"## {RULESV2_TITLE_EMOJI} Celestials Dragons | Rules\n"
                            " *** Welcome to Celestials Dragons! Please select your language to read the clan rules. ***\n"
                            "[Discord Terms of Service](https://discord.com/terms)"
                        ),
                    },
                    {"type": 14, "spacing": 2},
                    {
                        "type": 9,
                        "components": [
                            {"type": 10, "content": "<:emoji_44:1489765823533809674>  ** Selecciona Español **"}
                        ],
                        "accessory": {
                            "type": 2, "style": 5, "label": "Español",
                            "emoji": {"id": "1489666661228347526", "name": "Esp"},
                            "url": f"https://discord.com/channels/{GUILD_ID}/1489768820632588419",
                        },
                    },
                    {"type": 14, "divider": False},
                    {
                        "type": 9,
                        "components": [
                            {"type": 10, "content": "<:emoji_44:1489765823533809674> ** Select English **"}
                        ],
                        "accessory": {
                            "type": 2, "style": 5, "label": "English",
                            "emoji": {"id": "1489667788820971730", "name": "EEUU"},
                            "url": f"https://discord.com/channels/{GUILD_ID}/1489768537982500895",
                        },
                    },
                    {"type": 14},
                    {
                        "type": 9,
                        "components": [
                            {"type": 10, "content": "<:emoji_44:1489765823533809674> ** Selecione Português **"}
                        ],
                        "accessory": {
                            "type": 2, "style": 5, "label": "Português",
                            "emoji": {"id": "1489666119689306276", "name": "emoji_40"},
                            "url": f"https://discord.com/channels/{GUILD_ID}/1489769065135214704",
                        },
                    },
                    {"type": 14},
                    {"type": 10, "content": "** Check the other channels for more information. **"},
                ],
            },
            {
                "type": 17,
                "components": [
                    {
                        "type": 1,
                        "components": [
                            {
                                "type": 3,
                                "custom_id": "menu_canales",
                                "placeholder": "Channels",
                                "min_values": 1,
                                "max_values": 1,
                                "options": options,
                            }
                        ],
                    },
                ],
            },
        ],
    }

    try:
        await message.delete()
    except Exception:
        pass

    resp = await _discord_api_request(
        "POST", f"/channels/{message.channel.id}/messages", payload
    )
    if isinstance(resp, dict) and resp.get("message"):
        print(f"[rulesv2] API error: {resp}")


async def fetch_roblox_user(username: str) -> dict | None:
    async with aiohttp.ClientSession() as session:
        async with session.post(
            "https://users.roblox.com/v1/usernames/users",
            json={"usernames": [username], "excludeBannedUsers": False},
        ) as resp:
            data = await resp.json()
            if not data.get("data"):
                return None
            user = data["data"][0]
            user_id = user["id"]
            roblox_name = user["name"]

        async with session.get(
            f"https://thumbnails.roblox.com/v1/users/avatar-headshot"
            f"?userIds={user_id}&size=420x420&format=Png&isCircular=false"
        ) as resp:
            thumb_data = await resp.json()
            avatar_url = None
            if thumb_data.get("data"):
                avatar_url = thumb_data["data"][0].get("imageUrl")

    return {"name": roblox_name, "avatar": avatar_url}


_TIER_PHASE_ROLES: dict[int, str] = {
    1447047863736602777: "0",
    1447049414051889234: "1",
    1447050940187283648: "2",
    1447049536781418619: "3",
    1485358209760886894: "4",
    1485358385389113476: "5",
}

_TIER_SUBTIER_ROLES: dict[int, str] = {
    1447056957868478554: "High",
    1447056940856377434: "Mid",
    1447056922158039062: "Low",
}

_TIER_CLASS_ROLES: dict[int, str] = {
    1447057117533048985: "Strong",
    1447056992358105190: "Stable",
    1447056974934966353: "Weak",
}


def build_profile_embed(
    user: discord.Member | discord.User,
    roblox_data: dict | None,
    roblox_username: str,
) -> discord.Embed:
    role_ids = {r.id for r in getattr(user, "roles", [])}

    phase_num: str | None = None
    for rid, num in _TIER_PHASE_ROLES.items():
        if rid in role_ids:
            phase_num = num
            break

    subtier: str | None = None
    for rid, label in _TIER_SUBTIER_ROLES.items():
        if rid in role_ids:
            subtier = label
            break

    tier_class: str | None = None
    for rid, label in _TIER_CLASS_ROLES.items():
        if rid in role_ids:
            tier_class = label
            break

    region: str | None = None
    for rid, name in REGION_ROLES.items():
        if rid in role_ids:
            region = name
            break

    discord_tag = (
        f"{user.name}#{user.discriminator}"
        if user.discriminator != "0"
        else user.name
    )

    display_name = roblox_data["name"] if roblox_data else roblox_username
    roblox_link = f"[{display_name}](https://www.roblox.com/users/search?keyword={display_name})"

    embed = discord.Embed(title=user.display_name, color=0xFFB6C1)
    if roblox_data and roblox_data.get("avatar"):
        embed.set_thumbnail(url=roblox_data["avatar"])

    embed.add_field(name="Roblox", value=roblox_link, inline=True)
    embed.add_field(name="Discord", value=discord_tag, inline=True)

    if phase_num is not None:
        tier_value = " ".join(filter(None, [phase_num, subtier, tier_class]))
        embed.add_field(name="Tier", value=tier_value, inline=False)

    if region is not None:
        embed.add_field(name="Region", value=region, inline=False)

    streak_count = get_streak(user.id)
    embed.add_field(name="Streak", value=str(streak_count), inline=False)

    return embed


class LinkRobloxModal(discord.ui.Modal, title="Link Roblox Account"):
    roblox_input = discord.ui.TextInput(
        label="Enter your Roblox username",
        placeholder="Your exact Roblox username",
        min_length=1,
        max_length=50,
    )

    async def on_submit(self, interaction: discord.Interaction):
        username = self.roblox_input.value.strip()
        roblox_links[interaction.user.id] = username
        await interaction.response.defer()
        roblox_data = await fetch_roblox_user(username)
        embed = build_profile_embed(interaction.user, roblox_data, username)
        await interaction.followup.send(embed=embed)


class LinkRobloxView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Link Roblox Account",
        style=discord.ButtonStyle.danger,
        custom_id="link_roblox",
        row=0,
    )
    async def link_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(LinkRobloxModal())


async def handle_info(message: discord.Message):
    user_id = message.author.id

    if user_id not in roblox_links:
        prompt_embed = discord.Embed(
            description="You don't have a Roblox account linked yet.",
            color=0xFFB6C1,
        )
        await message.channel.send(embed=prompt_embed, view=LinkRobloxView())
        return

    roblox_username = roblox_links[user_id]
    roblox_data = await fetch_roblox_user(roblox_username)
    embed = build_profile_embed(message.author, roblox_data, roblox_username)
    await message.channel.send(embed=embed)


VALID_REGIONS = {"sp", "mi", "da", "cl", "la"}

REGION_DISPLAY = {
    "sp": "São Paulo, Brazil",
    "mi": "Miami, Florida",
    "da": "Dallas, Texas",
    "cl": "Los Angeles, California",
    "la": "Los Angeles, California",
}


async def handle_tier(message: discord.Message):
    author_role_ids = [r.id for r in message.author.roles]
    if TRYOUTER_ROLE_ID not in author_role_ids:
        await message.channel.send("You need the TRYOUTER role to use this command.")
        return

    raw = message.content

    note = ""
    note_match = re.search(r"note:\s*(.+)", raw, re.IGNORECASE)
    if note_match:
        note = note_match.group(1).strip()
        raw = raw[:note_match.start()].strip()

    content_no_mentions = re.sub(r"<@!?\d+>", "", raw).strip()
    parts = content_no_mentions.split()

    tier    = parts[1].lower() if len(parts) > 1 else ""
    subtier = parts[2].lower() if len(parts) > 2 else ""
    class_  = parts[3].lower() if len(parts) > 3 else ""

    _USAGE = "Usage: >tier <0-5|app> <low|mid|high> <weak|stable|strong> [@user] <sp|mi|da|cl|la> [note: text]"

    if tier not in VALID_TIERS:
        await message.channel.send(_USAGE)
        return
    if subtier not in VALID_SUBTIERS:
        await message.channel.send(_USAGE)
        return
    if class_ not in VALID_CLASSES:
        await message.channel.send(_USAGE)
        return

    region = ""
    for word in parts[4:]:
        if word.lower() in VALID_REGIONS:
            region = REGION_DISPLAY.get(word.lower(), word)
            break

    if not region:
        await message.channel.send(_USAGE)
        return

    target: discord.Member = message.mentions[0] if message.mentions else message.author
    guild = message.guild

    roles_to_remove = [
        guild.get_role(rid) for rid in ALL_TIER_ROLES
        if guild.get_role(rid) is not None
    ]
    await target.remove_roles(*roles_to_remove, reason=f"Tier reset by {message.author}")

    tier_role    = guild.get_role(TIER_ROLES[tier])
    subtier_role = guild.get_role(SUBTIER_ROLES[subtier])
    class_role   = guild.get_role(CLASS_ROLES[class_])

    roles_to_add = [r for r in [tier_role, subtier_role, class_role] if r is not None]
    await target.add_roles(*roles_to_add, reason=f"Tier set by {message.author}")

    display_tier = "App" if tier in ("app", "aplicant") else tier

    embed = discord.Embed(
        title="New Tier",
        description=(
            f"**New Tier:**\n"
            f"{target.mention} ¡Has been evaluated!\n\n"
            f"**Tier:** {display_tier} {subtier.capitalize()} {class_.capitalize()}\n\n"
            f"**Region:** {region}\n\n"
            f"**Notes:** {note if note else '-'}"
        ),
        color=TIER_COLORS[tier],
        timestamp=datetime.now(timezone.utc),
    )
    embed.set_footer(
        text=f"Evaluated by {message.author.display_name}",
        icon_url=message.author.display_avatar.url,
    )

    await message.channel.send(embed=embed)
if __name__ == "__main__":
    client.run(DISCORD_BOT_TOKEN)


