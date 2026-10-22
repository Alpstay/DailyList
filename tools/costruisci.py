"""Costruisce scatola.json per la piattaforma arrivi/partenze AlpStay.

Prende le pagine di `curated_operational_stays` lette da La Scatola e produce un
unico file da pubblicare. I soggiorni sono CIFRATI: il repository e' pubblico, e
l'elenco di chi dorme in quale camera e per quanti giorni non puo' stare in
chiaro su un indirizzo che chiunque puo' aprire. In chiaro restano solo i dati
di servizio (quando e' stato generato, la finestra, la freschezza), che servono
alla pagina per accendere il semaforo prima ancora di decifrare.

Uso:
  python3 tools/costruisci.py CHIAVE uscita.json soggiorni1.txt[,soggiorni2.txt,...] \
                              [intestatari1.txt,...] [letti1.txt,...]

Il terzo argomento sono le pagine di `curated_operational_stays`. Il quarto,
facoltativo, le pagine di `curated_guest_stays`: servono solo a prendere il
NOME DELL'INTESTATARIO, perche' la reception riconosce una prenotazione dal
nome, non dall'identificativo. Il nome finisce dentro la parte cifrata e mai
nei dati di servizio in chiaro.

Il quinto, pure facoltativo, le pagine di `curated_beds_daily`: la
disposizione dei letti, che decide la biancheria da preparare e il controllo
prima dell'arrivo. Fino a ottobre non esisteva e si tirava a indovinare dalla
tipologia di camera.

Ogni pagina e' la risposta grezza di La Scatola, cosi' come il sistema l'ha
salvata su file: {"data":[...], "freshness":{...}, "page":{...}}.
Se una pagina e' arrivata nel messaggio invece che su file, va salvata in un
file con la stessa forma, senza modificare nulla.

Gli ID di Slope si copiano identici: mai riscritti, mai normalizzati. Il
controllo sul formato UUID piu' sotto serve proprio a far fallire la
costruzione se un ID e' stato trascritto male.
"""
import base64
import datetime
import json
import os
import re
import sys

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

PROPRIETA = {
    '33333333-3333-4333-8333-333333333333': 'saslong',
    '22222222-2222-4222-8222-222222222222': 'hartmann',
    '11111111-1111-4111-8111-111111111111': 'acadia',
}
ROMA = datetime.timezone(datetime.timedelta(hours=2))   # Europe/Rome, ora legale
ITER = 250_000
UUID = re.compile(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}')

b64 = lambda b: base64.b64encode(b).decode()


def riga(r):
    """Una prenotazione, ridotta ai campi che la piattaforma usa davvero."""
    res = str(r.get('reservation_id') or '')
    ordine = str(r.get('order_id') or '')
    if not UUID.fullmatch(res):
        raise SystemExit('reservation_id non valido (trascritto male?): %r' % res)
    if ordine and not UUID.fullmatch(ordine):
        raise SystemExit('order_id non valido (trascritto male?): %r' % ordine)
    return {
        'rn': ('' if r.get('room_name') is None else str(r['room_name'])),
        'cin': r.get('arrival') or '',
        'cout': r.get('departure') or '',
        'adults': int(r.get('adults') or 0),
        'children': int(r.get('children') or 0),
        'opt': r.get('is_option') is True,
        'over': r.get('is_overbooking') is True,
        'resId': res,
        'orderId': ordine,
        # Stato e orari effettivi del soggiorno (La Scatola li espone da
        # meta' ottobre): TO_ARRIVE / IN_HOUSE / DEPARTED.
        'stato': str(r.get('stay_status') or ''),
        'inAt': str(r.get('check_in_at') or ''),
        'outAt': str(r.get('check_out_at') or ''),
    }


def intestatari(percorsi):
    """reservation_id -> "Cognome Nome" dell'intestatario della prenotazione."""
    nomi = {}
    for p in percorsi:
        if not p:
            continue
        d = json.load(open(p, encoding='utf-8'))
        for r in (d.get('data') or []):
            res = str(r.get('reservation_id') or '')
            if not UUID.fullmatch(res) or res in nomi:
                continue
            cog = (r.get('primary_guest_last_name') or '').strip()
            nom = (r.get('primary_guest_first_name') or '').strip()
            if not cog and not nom and r.get('is_primary_guest') is True:
                cog = (r.get('last_name') or '').strip()
                nom = (r.get('first_name') or '').strip()
            nome = ' '.join(y for y in (cog, nom) if y)
            if nome:
                nomi[res] = nome
    return nomi


# I nomi che Slope da' ai letti, tradotti nelle parole che la piattaforma gia'
# capisce: il calcolo della biancheria legge "matrimoniale", "singolo" e
# "a castello". KING e QUEEN sono matrimoniali a tutti gli effetti; il divano
# letto conta come un singolo, ma si scrive, perche' chi rifa' la stanza deve
# sapere che va aperto.
LETTI = {
    'DOUBLE': ('matrimoniale', 'matrimoniali'),
    'KING':   ('matrimoniale', 'matrimoniali'),
    'QUEEN':  ('matrimoniale', 'matrimoniali'),
    'SINGLE': ('singolo', 'singoli'),
    'SOFA':   ('singolo (divano letto)', 'singoli (divani letto)'),
    'BUNK':   ('a castello', 'a castello'),
}
ORDINE_LETTI = ['DOUBLE', 'KING', 'QUEEN', 'SINGLE', 'SOFA', 'BUNK']


def disposizione(percorsi):
    """reservation_id -> "1 matrimoniale + 1 singolo"."""
    conta = {}
    for p in percorsi:
        if not p:
            continue
        d = json.load(open(p, encoding='utf-8'))
        for r in (d.get('data') or []):
            res = str(r.get('reservation_id') or '')
            if not UUID.fullmatch(res):
                continue
            tipo = str(r.get('bed_type') or '').upper()
            try:
                q = int(r.get('quantity') or 0)
            except (TypeError, ValueError):
                q = 0
            if not tipo or q <= 0:
                continue
            conta.setdefault(res, {})
            if tipo in conta[res]:
                if conta[res][tipo] != q:
                    print('ATTENZIONE: quantita\' discordi per %s %s (%d vs %d), tengo la prima'
                          % (res, tipo, conta[res][tipo], q), file=sys.stderr)
                continue
            conta[res][tipo] = q
    fuori, out = set(), {}
    for res, m in conta.items():
        pezzi = []
        for tipo in ORDINE_LETTI + [k for k in sorted(m) if k not in ORDINE_LETTI]:
            q = m.get(tipo)
            if not q:
                continue
            if tipo in LETTI:
                uno, molti = LETTI[tipo]
                pezzi.append('%d %s' % (q, uno if q == 1 else molti))
            else:
                fuori.add(tipo)
                pezzi.append('%d %s' % (q, tipo.lower()))
        if pezzi:
            out[res] = ' + '.join(pezzi)
    for tipo in sorted(fuori):
        print("ATTENZIONE: tipo di letto sconosciuto %r, scritto com'e'" % tipo,
              file=sys.stderr)
    return out


def cifra(payload, chiave, contesto):
    """AES-GCM con chiave derivata dalla password, stesso schema delle altre
    app AlpStay. `contesto` entra come dato autenticato: un file rimesso in
    circolazione con un'altra data non si decifra."""
    salt, iv = os.urandom(16), os.urandom(12)
    key = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt,
                     iterations=ITER).derive(chiave.encode())
    ct = AESGCM(key).encrypt(iv, json.dumps(payload, ensure_ascii=False).encode(),
                             contesto.encode())
    return {'alg': 'AES-GCM/PBKDF2-SHA256', 'iter': ITER,
            'salt': b64(salt), 'iv': b64(iv), 'ct': b64(ct)}


def main():
    if len(sys.argv) < 4:
        raise SystemExit(__doc__)
    chiave, uscita, percorsi = sys.argv[1], sys.argv[2], sys.argv[3].split(',')
    nomi = intestatari(sys.argv[4].split(',')) if len(sys.argv) > 4 else {}
    letti = disposizione(sys.argv[5].split(',')) if len(sys.argv) > 5 else {}
    if len(chiave) < 12:
        raise SystemExit('chiave troppo corta: servono almeno 12 caratteri')

    strutture = {k: {'soggiorni': []} for k in PROPRIETA.values()}
    freschezza, visti, attesi = [], set(), None

    for p in percorsi:
        d = json.load(open(p, encoding='utf-8'))
        for r in (d.get('data') or []):
            chiave_prop = PROPRIETA.get(r.get('property_id'))
            if not chiave_prop:
                continue                      # struttura non nostra: si ignora
            rid = r.get('reservation_id')
            if rid in visti:                  # le pagine possono sovrapporsi
                continue
            visti.add(rid)
            x = riga(r)
            nome = nomi.get(x['resId'])
            if nome:
                x['guest'] = nome
            cfg = letti.get(x['resId'])
            if cfg:
                x['letti'] = cfg
            strutture[chiave_prop]['soggiorni'].append(x)
        pag = d.get('page') or {}
        if attesi is None:
            attesi = pag.get('total')
        if not freschezza:
            freschezza = (d.get('freshness') or {}).get('sources') or []

    totale = sum(len(s['soggiorni']) for s in strutture.values())
    # Completo significa: tante righe quante ne dichiara La Scatola. Il cursore
    # dell'ultima pagina non dice nulla, perche' le pagine possono essere lette
    # in piu' passate e in ordini diversi.
    incompleta = (attesi is None) or (totale != attesi)

    adesso = datetime.datetime.now(ROMA)
    giorno = adesso.date().isoformat()
    out = {
        'generato': adesso.isoformat(timespec='seconds'),
        'finestra': {'da': giorno,
                     'a': (adesso.date() + datetime.timedelta(days=30)).isoformat()},
        'incompleta': incompleta,
        'freschezza': freschezza,
        'dati': cifra({'strutture': strutture}, chiave, giorno),
    }
    with open(uscita, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, separators=(',', ':'))

    con_nome = sum(1 for s in strutture.values() for x in s['soggiorni'] if x.get('guest'))
    con_letti = sum(1 for s in strutture.values() for x in s['soggiorni'] if x.get('letti'))
    print('RIEPILOGO %s: %d soggiorni (attesi %s) · %d con intestatario · %d con letti · incompleta=%s · %d byte'
          % (uscita, totale, attesi, con_nome, con_letti, incompleta, os.path.getsize(uscita)), file=sys.stderr)
    for k, s in strutture.items():
        arr = sum(1 for x in s['soggiorni'] if x['cin'] == giorno)
        par = sum(1 for x in s['soggiorni'] if x['cout'] == giorno)
        usciti = sum(1 for x in s['soggiorni'] if x['cout'] == giorno and x['stato'] == 'DEPARTED')
        print('RIEPILOGO   %-9s %4d soggiorni · oggi %d arrivi, %d partenze (%d gia\' uscite)'
              % (k, len(s['soggiorni']), arr, par, usciti), file=sys.stderr)
    if incompleta:
        print('ATTENZIONE: elenco incompleto, mancano delle pagine', file=sys.stderr)


if __name__ == '__main__':
    main()
