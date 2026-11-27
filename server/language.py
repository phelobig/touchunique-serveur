# -*- coding: utf-8 -*-
"""Base de langue FR/EN côté serveur — miroir de shared/tus-language.js.

Cette bibliothèque est volontairement autonome (bibliothèque standard Python
uniquement). Elle fournit :

* ``detect(text)``   : détection simple FR/EN (FR par défaut) ;
* ``name(code)`` / ``languages()`` : métadonnées ;
* ``system(extra, lang)`` : consigne système complète de l'assistant officiel ;
* ``phrase(key, lang, **vars)`` : texte localisé (intention ou texte technique) ;
* ``reply(text, lang, ctx)`` : réponse locale honnête, PR/EN.

Règles communes aux deux langues (identiques au client) : assistant officiel
Touch Unique Studio, Burkina-Faso, contact WhatsApp https://wa.me/22655041530,
aucune publication ni paiement présenté comme effectué s'il ne l'est pas.
"""

import os
import re
import unicodedata

LANGS = ("fr", "en")
WHATSAPP_URL = "https://wa.me/22655041530"


def normalize_lang(code=None):
    """Normalise un code locale ('fr-FR', 'EN_us', 'français') en 'fr'/'en'."""
    raw = str(code or "").strip().lower()
    if raw.startswith("en") or "english" in raw or raw in ("anglais", "english"):
        return "en"
    return "fr"


DEFAULT_LANG = normalize_lang(os.environ.get("TUS_DEFAULT_LANG", "fr"))


def _fold(text):
    """Minuscule sans accents : matching tolérant FR/EN."""
    decomposed = unicodedata.normalize("NFKD", str(text or ""))
    return "".join(c for c in decomposed if not unicodedata.combining(c)).lower()


def detect(text):
    """Détecte la langue d'un texte. Le français reste le défaut."""
    raw = str(text or "")
    folded = _fold(raw)
    if not folded.strip():
        return DEFAULT_LANG
    fr_markers = (
        "bonjour", "bonsoir", "salut", "merci", "s'il vous plait", "s il vous plait",
        "je voudrais", "je veux", "nous voulons", "pouvez-vous", "pouvez vous",
        "peux-tu", "quel est", "quelle est", "quels sont", "quelles sont",
        "combien coute", "combien", "pourquoi", "comment", "ou pouvez",
        "veuillez", "disponible", "devis", "offres", "services", "projet",
        "realiser", "produire", "livraison", "francais", "burkina", "nous",
        "vous", "votre", "nos", "est-ce", "j'ai", "n'ai",
    )
    en_markers = (
        "hello", "hi there", "good morning", "thanks", "thank you", "please",
        "can you", "could you", "would you", "i want", "i need", "we need",
        "what is", "which service", "how much", "why", "how do", "where can",
        "do you", "does it", "your", "our", "quote", "pricing", "price",
        "delivery", "project", "available", "english", "france", "yes", "no",
        "research", "sources", "analyze", "publish", "post", "visitor", "account",
    )
    fr_score = sum(1 for marker in fr_markers if marker in folded)
    en_score = sum(1 for marker in en_markers if marker in folded)
    # Les accents et la digraphie « œ » sont des signaux francophones fiables.
    if re.search(r"[\u00e0\u00e2\u00e7\u00e9\u00e8\u00ea\u00eb\u00f4\u00f9\u00fb\u00fc\u0153]", raw):
        fr_score += 2
    if re.search(r"\benglish\b|\bin english\b", folded):
        en_score += 3
    if re.search(r"\bfrancais\b|\ben francais\b|\bfran\u00e7ais\b", raw.lower()):
        fr_score += 3
    if en_score > fr_score:
        return "en"
    if fr_score > 0:
        return "fr"
    return DEFAULT_LANG


def name(code=None):
    """Nom lisible d'un code de langue."""
    return {"fr": "Français", "en": "English"}[normalize_lang(code)]


def languages():
    """Liste des langues prises en charge, ordre préféré (FR puis EN)."""
    return list(LANGS)


# ---------------------------------------------------------------------------
# Consignes système et textes techniques
# ---------------------------------------------------------------------------

TEXTS = {
    "system": {
        "fr": (
            "Tu es l'assistant officiel de Touch Unique Studio, studio créatif au Burkina-Faso. "
            "Réponds en français, de façon utile, précise et concise. Domaines : identité visuelle, "
            "vidéo, réseaux sociaux, print, académie, automatisation IA, outils et logiciels "
            "informatiques, prospection. Cite le contact officiel WhatsApp https://wa.me/22655041530 "
            "quand un échange humain est utile. Ne promets jamais une publication ou un paiement que tu "
            "n'as pas réellement effectué. Si tu ne sais pas, dis-le."
        ),
        "en": (
            "You are the official assistant of Touch Unique Studio, a creative studio in Burkina Faso. "
            "Reply in English, helpfully, accurately and concisely. Areas: visual identity, video, "
            "social media, print, academy, AI automation, software tools and prospecting. Share the "
            "official WhatsApp contact https://wa.me/22655041530 when a human conversation helps. Never claim "
            "that a post was published or a payment was made unless it really was. If you do not know, "
            "say so."
        ),
    },
    "extra_intro": {
        "fr": "Consigne complémentaire de l'utilisateur (à appliquer si elle reste honnête) :",
        "en": "Additional user instruction (apply it only if it stays truthful):",
    },
    "guarantee": {
        "fr": "Garanties : aucune publication, aucun paiement et aucune certification ne sont simulés.",
        "en": "Guarantees: no publication, payment or certification is ever simulated.",
    },
    "context_intro": {
        "fr": "Contexte Internet vérifié (Wikipédia) :",
        "en": "Verified Internet context (Wikipedia):",
    },
    "context_use": {
        "fr": "Utilise le contexte suivant s'il est utile, en restant exact.",
        "en": "Use the following context if helpful, and stay accurate.",
    },
    "rate_limit": {
        "fr": "Trop de requêtes IA en une minute ({limit}/min par adresse IP). Le service est gratuit et illimité ; réessayez dans un instant.",
        "en": "Too many AI requests in one minute ({limit}/min per IP address). The service is free and unlimited; try again in a moment.",
    },
    "unavailable": {
        "fr": "Les fournisseurs IA sont momentanément indisponibles. Écrivez-nous sur WhatsApp : " + WHATSAPP_URL,
        "en": "AI providers are temporarily unavailable. Message us on WhatsApp: " + WHATSAPP_URL,
    },
    "sources": {"fr": "Sources vérifiables :", "en": "Verifiable sources:"},
    "media_system": {
        "fr": (
            "Tu es l'analyste multimédia de Touch Unique Studio au Burkina-Faso. "
            "Examines le fichier fourni avec précision et neutralité. "
            "Extrais uniquement ce qui est réellement visible ou audible, sans rien inventer. "
            "Signale explicitement ce qui est illisible, ambigu ou non vérifiable. "
            "Réponds en français, sous forme de JSON valide avec les clés : "
            "summary (2 phrases), details (liste de faits observés), "
            "entities (objet avec names, organisations, phones, emails, dates, amounts, urls — listes), "
            "suggestedMission (une phrase d'objectif actionnable), "
            "confidence (elevee/moyenne/faible). Aucune publication ni paiement n'est à simuler."
        ),
        "en": (
            "You are the media analyst of Touch Unique Studio in Burkina Faso. "
            "Examine the provided file accurately and neutrally. "
            "Extract only what is truly visible or audible; invent nothing. "
            "Explicitly flag anything unreadable, ambiguous or unverifiable. "
            "Reply in English as valid JSON with the keys: "
            "summary (2 sentences), details (list of observed facts), "
            "entities (object with names, organisations, phones, emails, dates, amounts, urls — lists), "
            "suggestedMission (one actionable objective sentence), "
            "confidence (high/medium/low). Never simulate a publication or a payment."
        ),
    },
    "media_fallback": {
        "fr": (
            "Tu es l'analyste multimédia de Touch Unique Studio. Décris précisément le fichier, "
            "extrais uniquement les informations réellement lisibles (noms, contacts, dates, montants, "
            "besoins) et propose une mission de création ou de prospection. Ne prétends jamais avoir "
            "contacté quelqu'un ni publié quelque chose. Réponds en français avec des titres clairs."
        ),
        "en": (
            "You are the media analyst of Touch Unique Studio. Describe the file precisely, extract "
            "only genuinely readable information (names, contacts, dates, amounts, needs) and suggest "
            "a creation or prospecting task. Never claim to have contacted anyone or published anything. "
            "Reply in English with clear headings."
        ),
    },
    "media_question": {
        "fr": "Analyse ce fichier {kind} pour une mission de Touch Unique Studio. Extrais uniquement les faits exploitables et réponds en JSON selon la consigne.",
        "en": "Analyze this {kind} file for a Touch Unique Studio task. Extract only usable facts and reply as JSON according to the instruction.",
    },
    "media_document": {
        "fr": "Contenu du document :",
        "en": "Document content:",
    },
    "media_transcript": {
        "fr": "Transcription :",
        "en": "Transcript:",
    },
    "media_json_task": {
        "fr": "Transforme l'analyse suivante en JSON strict selon cette consigne :",
        "en": "Turn the following analysis into strict JSON according to this instruction:",
    },
    "media_json_only": {
        "fr": "Réponds uniquement avec un objet JSON valide.",
        "en": "Reply with a valid JSON object only.",
    },
    "media_binary": {
        "fr": "Document binaire : aucun texte extractible localement.",
        "en": "Binary document: no text extractable locally.",
    },
    "media_local_extract": {
        "fr": "Texte extrait localement : {count} caractères.",
        "en": "Text extracted locally: {count} characters.",
    },
    "media_summary": {
        "fr": "Fichier {kind} analysé : {name}",
        "en": "Analyzed {kind} file: {name}",
    },
    "media_error": {
        "fr": "Analyse indisponible : {error}",
        "en": "Analysis unavailable: {error}",
    },
    "media_confidence": {
        "fr": "faible",
        "en": "low",
    },
    "media_not_specified": {
        "fr": "non précisée",
        "en": "not specified",
    },
    "media_no_audio": {
        "fr": "Analyse audio impossible : connectez OpenAI (Whisper) ou Gemini.",
        "en": "Audio analysis unavailable: connect OpenAI (Whisper) or Gemini.",
    },
    "media_no_image": {
        "fr": "Analyse d'image impossible : connectez Gemini, OpenAI ou Claude.",
        "en": "Image analysis unavailable: connect Gemini, OpenAI or Claude.",
    },
    "media_no_video": {
        "fr": "Analyse vidéo impossible : connectez Gemini (compréhension vidéo native).",
        "en": "Video analysis unavailable: connect Gemini (native video understanding).",
    },
    "media_no_type": {
        "fr": "Type de fichier non pris en charge pour l'analyse : {kind}",
        "en": "File type not supported for analysis: {kind}",
    },
}


def system(extra="", lang=None):
    """Consigne système complète dans la langue demandée, plus un complément."""
    code = normalize_lang(lang)
    base = TEXTS["system"][code]
    addition = str(extra or "").strip()[:2000]
    if addition:
        base += "\n" + TEXTS["extra_intro"][code] + " " + addition
    return base + "\n" + TEXTS["guarantee"][code]


# ---------------------------------------------------------------------------
# Intentions traduites (miroir de TUSLanguage.intents côté client)
# ---------------------------------------------------------------------------

INTENTS = {
    "greeting": {
        "fr": "Bonjour ! Je suis l'assistant officiel Touch Unique Studio, au Burkina-Faso. Comment puis-je vous aider aujourd'hui ?",
        "en": "Hello! I am the official Touch Unique Studio assistant, based in Burkina Faso. How can I help you today?",
    },
    "goodbye": {
        "fr": "À bientôt ! Pour une réponse personnalisée, écrivez-nous sur WhatsApp : " + WHATSAPP_URL,
        "en": "Goodbye! For a personal reply, message us on WhatsApp: " + WHATSAPP_URL,
    },
    "thanks": {
        "fr": "Avec plaisir. Si vous voulez aller plus loin, parlez-nous de votre projet ou écrivez-nous sur WhatsApp : " + WHATSAPP_URL,
        "en": "You're welcome. To go further, tell us about your project or message us on WhatsApp: " + WHATSAPP_URL,
    },
    "help": {
        "fr": "Je peux vous expliquer nos services, préparer un brief, proposer des idées de publication, de visuel ou de prospection et effectuer une recherche factuelle avec ses sources. Que souhaitez-vous faire ?",
        "en": "I can explain our services, draft a brief, suggest post, design or prospecting ideas, and run a factual search with sources. What would you like to do?",
    },
    "services": {
        "fr": "Touch Unique Studio propose : identité visuelle, vidéo et motion, contenus pour réseaux sociaux, print et packaging, académie, automatisation IA, outils logiciels et accompagnement commercial. Le catalogue complet est disponible sur le site.",
        "en": "Touch Unique Studio offers: visual identity, video and motion, social media content, print and packaging, academy, AI automation, software tools and business support. The full catalogue is on the website.",
    },
    "about": {
        "fr": "Touch Unique Studio est un studio créatif basé au Burkina-Faso. Nous accompagnons les entreprises et les créateurs de l'identité à la diffusion, avec une équipe et des outils d'automatisation.",
        "en": "Touch Unique Studio is a creative studio based in Burkina Faso. We support businesses and creators from identity to distribution, with a team and automation tools.",
    },
    "identity": {
        "fr": "Pour une identité visuelle, nous travaillons généralement : brief, deux propositions de logo, palette et typographies, mini-charte, puis déclinaisons après validation. Rien n'est livré avant votre accord.",
        "en": "For visual identity, we usually work through: brief, two logo proposals, colours and typography, a mini brand guide, then variants after approval. Nothing is delivered before your agreement.",
    },
    "video": {
        "fr": "Nous produisons des vidéos courtes pour réseaux sociaux, des clips de présentation et du motion design. Indiquez le format, la durée et le message souhaité ; nous préparerons un plan précis.",
        "en": "We produce short social videos, presentation clips and motion design. Tell us the format, length and message; we will prepare a precise plan.",
    },
    "social": {
        "fr": "Pour les réseaux sociaux, nous pouvons préparer un calendrier éditorial, des légendes, des visuels et des idées de formats. La publication n'est effectuée qu'après votre validation explicite et confirmation renvoyée par le réseau.",
        "en": "For social media, we can prepare an editorial calendar, captions, visuals and format ideas. Posting happens only after your explicit approval and a confirmation returned by the platform.",
    },
    "print": {
        "fr": "Nous concevons aussi des supports print : cartes, affiches, flyers, packaging et signalétique. Donnez le format, le tirage et l'usage ; nous vérifierons les contraintes techniques.",
        "en": "We also design print material: business cards, posters, flyers, packaging and signage. Give the format, print run and purpose; we will check the technical constraints.",
    },
    "academy": {
        "fr": "L'académie Touch Unique propose des formations pratiques sur la création, les réseaux sociaux, la vidéo et les outils IA. Les sessions sont définies avec vous selon votre niveau.",
        "en": "The Touch Unique academy offers hands-on training in design, social media, video and AI tools. Sessions are defined with you according to your level.",
    },
    "ai_automation": {
        "fr": "Nous automatisons les tâches répétitives : tri de prospects, briefs, rédaction de contenus, suivi de messages et organisation de fichiers. Chaque action reste visible et validable dans l'application.",
        "en": "We automate repetitive tasks: lead sorting, briefs, content drafting, message follow-up and file organisation. Every action stays visible and reviewable in the app.",
    },
    "software": {
        "fr": "Nous créons ou améliorons des outils logiciels simples : sites, tableaux de bord, petites applications métier et intégrations. Décrivez le problème à résoudre et nous proposerons une approche.",
        "en": "We build or improve practical software tools: websites, dashboards, small business apps and integrations. Describe the problem and we will suggest an approach.",
    },
    "pricing": {
        "fr": "Les prix affichés dans le catalogue sont des prix de départ en FCFA. Le montant final est confirmé par un devis gratuit, après discussion du périmètre. Aucun paiement n'est demandé ni confirmé par ce chat.",
        "en": "Catalogue prices are starting prices in FCFA. The final amount is confirmed by a free quote after discussing the scope. No payment is requested or confirmed in this chat.",
    },
    "quote": {
        "fr": "Pour préparer un devis gratuit, indiquez le service souhaité, le format, le délai et votre budget approximatif. Vous pouvez aussi nous écrire sur WhatsApp : " + WHATSAPP_URL,
        "en": "To prepare a free quote, tell us the service, format, deadline and approximate budget. You can also message us on WhatsApp: " + WHATSAPP_URL,
    },
    "contact": {
        "fr": "Vous pouvez joindre Touch Unique Studio sur WhatsApp au https://wa.me/22655041530. Laissez un message avec votre besoin et un membre de l'équipe vous répondra.",
        "en": "You can reach Touch Unique Studio on WhatsApp at https://wa.me/22655041530. Leave a message with your need and a team member will reply.",
    },
    "whatsapp": {
        "fr": "Le contact officiel WhatsApp est https://wa.me/22655041530 (Burkina-Faso).",
        "en": "The official WhatsApp contact is https://wa.me/22655041530 (Burkina Faso).",
    },
    "location": {
        "fr": "Touch Unique Studio est basé au Burkina-Faso et travaille avec des clients locaux et internationaux à distance.",
        "en": "Touch Unique Studio is based in Burkina Faso and works with local and international clients remotely.",
    },
    "hours": {
        "fr": "Les horaires exacts sont confirmés par l'équipe. Pour une réponse rapide, écrivez sur WhatsApp : " + WHATSAPP_URL,
        "en": "Opening hours are confirmed by the team. For a quick reply, message WhatsApp: " + WHATSAPP_URL,
    },
    "process": {
        "fr": "Notre processus : échange sur le besoin, devis gratuit, brief, conception, validation, livraison puis suivi. Chaque étape est enregistrée dans l'application.",
        "en": "Our process: discuss the need, free quote, brief, design, approval, delivery then follow-up. Each step is recorded in the app.",
    },
    "deliverables": {
        "fr": "Les livrables dépendent de l'offre : fichiers sources et exports, charte, formats réseaux, vidéos, documents ou formation. La liste précise figure dans chaque fiche du catalogue.",
        "en": "Deliverables depend on the offer: source files and exports, brand guide, social formats, videos, documents or training. The exact list is on each catalogue item.",
    },
    "timeline": {
        "fr": "Les délais indicatifs sont affichés sur chaque offre du catalogue ; le calendrier définitif est validé avec vous avant le démarrage.",
        "en": "Indicative timelines are shown on each catalogue offer; the final schedule is agreed with you before work starts.",
    },
    "publication": {
        "fr": "Je peux préparer le texte et le visuel d'une publication, mais je ne publie rien sans votre validation explicite. Une publication n'est annoncée que si le réseau renvoie un identifiant réel.",
        "en": "I can draft the copy and visual for a post, but I publish nothing without your explicit approval. A post is announced only if the platform returns a real identifier.",
    },
    "payment": {
        "fr": "Aucun paiement n'est effectué ni confirmé dans ce chat. Les conditions et le moyen de paiement sont communiqués par l'équipe après validation du devis.",
        "en": "No payment is made or confirmed in this chat. Terms and payment method are provided by the team after the quote is approved.",
    },
    "refund": {
        "fr": "Les conditions de remboursement sont celles communiquées par Touch Unique Studio dans le devis. Ce chat ne peut pas décider ni confirmer un remboursement.",
        "en": "Refund conditions are those communicated by Touch Unique Studio in the quote. This chat cannot decide or confirm a refund.",
    },
    "account": {
        "fr": "Les comptes et préférences sont gérés localement dans l'application. Les secrets et tokens restent côté serveur et ne sont jamais affichés au navigateur.",
        "en": "Accounts and preferences are managed locally in the app. Secrets and tokens stay on the server and are never shown to the browser.",
    },
    "drive": {
        "fr": "Google Drive peut être connecté depuis les réglages de l'application pour sauvegarder les fichiers du studio. La connexion doit être autorisée explicitement ; aucune sauvegarde n'est simulée.",
        "en": "Google Drive can be connected from the app settings to back up studio files. Access must be explicitly authorised; no backup is simulated.",
    },
    "messages": {
        "fr": "La messagerie du site transmet vos questions à l'application de gestion. Une réponse n'est affichée que lorsqu'elle a réellement été envoyée par l'équipe.",
        "en": "The website messaging forwards your questions to the management app. A reply appears only when the team has actually sent it.",
    },
    "research": {
        "fr": "Je peux effectuer une recherche factuelle côté serveur et citer des sources ouvertes vérifiables (Wikipédia). Je signale ce qui n'est pas confirmé.",
        "en": "I can run a factual search on the server and cite verifiable open sources (Wikipedia). I flag anything unconfirmed.",
    },
    "prospect": {
        "fr": "Je peux proposer des pistes de prospection et une approche personnalisée, à partir d'éléments observables. Je ne prétends jamais avoir contacté une structure.",
        "en": "I can suggest prospects and a personalised approach based on observable signals. I never claim to have contacted an organisation.",
    },
    "design": {
        "fr": "Pour un visuel, je précise : objectif, format, hiérarchie de l'information, palette rouge sur fond clair et livrables attendus. Les fichiers sont produits après validation.",
        "en": "For a visual, I specify: goal, format, information hierarchy, red-on-light palette and expected deliverables. Files are produced after approval.",
    },
    "media_analysis": {
        "fr": "Vous pouvez envoyer une image, un audio, une vidéo ou un document : l'analyse ne décrit que ce qui est réellement visible ou audible et signale ce qui est illisible.",
        "en": "You can send an image, audio, video or document: the analysis describes only what is truly visible or audible and flags anything unreadable.",
    },
    "status": {
        "fr": "Le serveur expose son état dans /api/status : langues fr et en, fournisseurs IA connectés et réseaux sociaux connectés. Seuls des indicateurs booléens sont publics, jamais les clés.",
        "en": "The server exposes its state at /api/status: fr and en languages, connected AI providers and social networks. Only boolean indicators are public, never the keys.",
    },
    "capabilities": {
        "fr": "L'assistant IA de Touch Unique Studio fonctionne avec un accès Internet côté serveur, sans quota ni essai limité. Une limite technique très large protège seulement contre les abus.",
        "en": "The Touch Unique Studio AI assistant runs with server-side Internet access, with no quota or limited trial. A very wide technical limit only protects against abuse.",
    },
    "limits": {
        "fr": "Je ne promets aucun résultat garanti, aucune publication non effectuée et aucun paiement simulé. Si une information n'est pas vérifiable, je le dis clairement.",
        "en": "I promise no guaranteed outcome, no unpublished post and no simulated payment. If information cannot be verified, I say so clearly.",
    },
    "language": {
        "fr": "Je réponds en français ou en anglais. La langue est détectée automatiquement ou fournie par le client avec le champ « lang ».",
        "en": "I reply in French or English. The language is detected automatically or provided by the client with the 'lang' field.",
    },
    "catalog": {
        "fr": "Le catalogue présente les offres par catégorie avec prix de départ, délais et livrables. Le site et l'application affichent le même catalogue lorsqu'ils sont synchronisés.",
        "en": "The catalogue lists offers by category with starting prices, timelines and deliverables. The website and app show the same catalogue when synced.",
    },
    "visit": {
        "fr": "Le compteur de visiteurs est calculé côté serveur et affiché sur le site ; aucune donnée personnelle n'est requise pour le consulter.",
        "en": "The visitor counter is computed on the server and shown on the website; no personal data is needed to view it.",
    },
    "agents": {
        "fr": "Le pipeline collaborative organise une mission en quatre étapes : recherche, conception, production et livraison. Chaque étape reste modifiable.",
        "en": "The collaborative pipeline organises a task into four stages: research, design, production and delivery. Every stage stays editable.",
    },
    "fallback": {
        "fr": "Je n'ai pas de réponse vérifiée à cette question. Décrivez précisément votre besoin ou écrivez-nous sur WhatsApp : " + WHATSAPP_URL,
        "en": "I don't have a verified answer to that question. Describe your need precisely or message us on WhatsApp: " + WHATSAPP_URL,
    },
}


# Motifs de détection d'intention (français et anglais, sans accents).
PATTERNS = {
    "greeting": (r"\bbonjour\b|\bsalut\b|\bhello\b|\bhi\b|\bbonsoir\b|\bgood morning\b",),
    "goodbye": (r"\ba bientot\b|\bau revoir\b|\bgoodbye\b|\bbye\b",),
    "thanks": (r"\bmerci\b|\bthank you\b|\bthanks\b",),
    "help": (r"\baide\w*\b|\bhelp\b|\bque pouvez\b|\bwhat can you\b",),
    "whatsapp": (r"\bwhatsapp\b|\b22655041530\b",),
    "contact": (r"\bcontact\b|\bjoindre\b|\bappeler\b|\bcall you\b|\breach you\b|\btelephone\b|\bphone\b",),
    "pricing": (r"\bprix\b|\btarif\w*\b|\bcombien coute\b|\bprice\b|\bpricing\b|\bhow much\b|\bcout\b",),
    "quote": (r"\bdevis\b|\bquote\b|\bestimation\b|\bestimate\b",),
    "payment": (r"\bpaiement\w*\b|\bpayer\b|\bfactur\w*\b|\bpayment\b|\bpay\b|\binvoice\b|\bcarte bancaire\b",),
    "refund": (r"\brembours\w*\b|\brefund\b|\bmoney back\b",),
    "publication": (r"\bpublier\b|\bpublication\b|\bposter\b|\bposts?\b|\bpublish\b|\bpartager\b",),
    "research": (r"\brecherch\w*\b|\bveille\w*\b|\bcherch\w*\b|\bfind out\b|\bresearch\b|\bsources?\b|\binternet\b",),
    "prospect": (r"\bprospect\b|\bpiste\b|\bclient potentiel\b|\blead\b|\bprospection\b",),
    "design": (r"\bvisuel\b|\bdesign\b|\baffiche\b|\bidentite\b|\blogo\b|\bcharte\b|\bmaquette\b",),
    "video": (r"\bvideo\b|\bfilm\b|\bmotion\b|\bclip\b|\breel\b",),
    "social": (r"\breseaux sociaux\b|\bsocial media\b|\binstagram\b|\bfacebook\b|\blinkedin\b|\btiktok\b",),
    "print": (r"\bprint\b|\bflyer\b|\baffiche\b|\bpackaging\b|\bcarte de visite\b|\bbusiness card\b",),
    "academy": (r"\bacademie\b|\bformation\b|\bcours\b|\btraining\b|\bacademy\b|\bapprendre\b",),
    "ai_automation": (r"\bautomatisation\b|\bautomatique\b|\bagents?\b|\brobot\b|\bautomation\b|\bworkflow\b",),
    "software": (r"\blogiciel\b|\boutil\b|\bapplication\b|\bsite web\b|\bsoftware\b|\btool\b|\bapp\b|\bdashboard\b",),
    "media_analysis": (r"\bimage\b|\bphoto\b|\baudio\b|\bson\b|\bfichier\b|\bdocument\b|\bvideo\b|\bpdf\b|\banalyser\b|\banalyze\b",),
    "drive": (r"\bdrive\b|\bgoogle\b|\bsauvegarde\b|\bbackup\b|\bcloud\b",),
    "messages": (r"\bmessagerie\b|\bmessage\b|\bdiscussion\b|\bconversation\b|\binbox\b",),
    "agents": (r"\bpipeline\b|\bmission\b|\bagent\b|\bétapes\b|\betapes\b|\bworkflow\b",),
    "catalog": (r"\bcatalogue\b|\boffres?\b|\bservices? disponibles\b|\bcatalog\b|\boffers?\b",),
    "location": (r"\bburkina\b|\bouagadougou\b|\bobijari\b|\blocalisation\b|\bwhere are you\b|\blocated\b",),
    "hours": (r"\bhoraire\b|\bquand\b|\bopening\b|\bhours\b|\bdisponible quand\b",),
    "deliverables": (r"\blivrable\w*\b|\bfichiers?\b|\bce que je recois\b|\bdeliverable\w*\b|\bfiles\b",),
    "timeline": (r"\bdelai\w*\b|\bquand\b|\btemps\b|\bdelay\b|\btimeline\b|\bhow long\b",),
    "process": (r"\bprocessus\b|\betapes\b|\bcomment travaillez\b|\bprocess\b|\bhow do you work\b",),
    "status": (r"\bstatut\b|\betat du serveur\b|\bstatus\b|\bconnecte\b|\bconfigured\b",),
    "capabilities": (r"\billimite\b|\bgratuit\b|\bquota\b|\bessai\b|\bunlimited\b|\bfree\b|\btrial\b",),
    "limits": (r"\bpromesse\b|\bgarantie\b|\bvrai\b|\breellement\b|\bverify\b|\bverifi\w*\b|\bfake\b",),
    "language": (r"\blangue\b|\bfrancais\b|\benglish\b|\banglais\b|\blanguage\b|\btranslate\b|\btraduire\b",),
    "visit": (r"\bvisiteur\b|\bvisites\b|\bcompteur\b|\bvisitors?\b|\bviews\b",),
    "about": (r"\bqui etes\b|\bsociete\b|\bentreprise\b|\babout\b|\bwho are you\b|\bstudio\b",),
    "account": (r"\bcompte\b|\bconnexion\b|\blogin\b|\baccount\b|\bsecret\b|\bcle\b|\bkey\b",),
    "services": (r"\bservices?\b|\bque faites\b|\bque proposez\b|\boffrez\b|\bwhat do you offer\b|\bcapabilities\b",),
    "fallback": (r".",),
}


_COMPILED = {key: tuple(re.compile(pattern) for pattern in patterns)
             for key, patterns in PATTERNS.items()}


def _fill(template, values):
    """Remplace uniquement les variables fournies, sans erreur sur les autres."""
    text = str(template)
    for key, value in values.items():
        text = text.replace("{" + str(key) + "}", str(value))
    return text


def phrase(key, lang=None, **vars):
    """Retourne un texte localisé ;FR par défaut, sans jamais lever de secret."""
    code = normalize_lang(lang)
    entry = INTENTS.get(key) or TEXTS.get(key)
    if not entry:
        entry = INTENTS["fallback"]
    if isinstance(entry, dict):
        text = entry.get(code) or entry.get("fr") or next(iter(entry.values()))
    else:
        text = str(entry)
    return _fill(text, vars)


def reply(text, lang=None, ctx=None):
    """Réponse locale honnête à une question, éventuellement enrichie par un contexte réel.

    ``ctx`` peut contenir ``sources`` (liste de {title, url} réellement obtenus),
    ``available`` (False si aucun fournisseur n'a répondu) ou toute variable
    utilisée par une intention. Aucune valeur de secret n'est acceptée ni
    renvoyée : seules les clés et valeurs utiles à l'affichage sont filtrées.
    """
    code = normalize_lang(lang) if lang else detect(text)
    folded = _fold(text)
    best, best_score = "fallback", 0
    for intent, patterns in _COMPILED.items():
        score = sum(1 for pattern in patterns if pattern.search(folded))
        if score > best_score:
            best, best_score = intent, score
            if score >= 2:
                break
    context = ctx if isinstance(ctx, dict) else {}
    if context.get("available") is False:
        return TEXTS["unavailable"][code]
    safe = {k: v for k, v in context.items()
            if isinstance(k, str) and isinstance(v, (str, int, float, bool))}
    result = phrase(best, code, **safe)
    sources = context.get("sources")
    if isinstance(sources, (list, tuple)):
        links = []
        for item in sources[:3]:
            if isinstance(item, dict):
                url = str(item.get("url") or "").strip()
                title = str(item.get("title") or url).strip()[:80]
            else:
                url, title = str(item).strip(), str(item).strip()[:80]
            if url.startswith(("https://", "http://")):
                links.append("- " + title + " — " + url[:500])
        if links:
            result += "\n\n" + TEXTS["sources"][code] + "\n" + "\n".join(links)
    return result.strip()
