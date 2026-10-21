"""Controlla scatola.json prima di pubblicarlo.

Serve a non mandare online un file peggiore di quello che c'e' gia'. Meglio
lasciare alla reception i dati dell'ora prima che darle un elenco vuoto o
troncato senza che nessuno se ne accorga.

Uso:
  python3 tools/verifica.py CHIAVE scatola.json [minimo_soggiorni]

Finisce con "verifica OK" solo se tutti i controlli passano; altrimenti esce
con errore e la pubblicazione va fermata.
"""
import base64
import datetime
import json
import re
import sys

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

ROMA = datetime.timezone(datetime.timedelta(hours=2))
UUID = re.compile(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}')
STATI = {'', 'TO_ARRIVE', 'IN_HOUSE', 'DEPARTED'}


def guasto(msg):
    print('VERIFICA FALLITA: ' + msg, file=sys.stderr)
    raise SystemExit(1)


def main():
    if len(sys.argv) < 3:
        raise SystemExit(__doc__)
    chiave, percorso = sys.argv[1], sys.argv[2]
    minimo = int(sys.argv[3]) if len(sys.argv) > 3 else 1

    d = json.load(open(percorso, encoding='utf-8'))
    for campo in ('generato', 'finestra', 'incompleta', 'dati'):
        if campo not in d:
            guasto('manca il campo "%s"' % campo)

    if d['incompleta']:
        guasto('il file e\' segnato incompleto')

    # Il file non deve contenere soggiorni in chiaro: se li trovo, la
    # cifratura non ha funzionato e il file non va pubblicato.
    testo = json.dumps(d, ensure_ascii=False)
    if '"strutture"' in testo or '"resId"' in testo:
        guasto('dati dei soggiorni in chiaro nel file')

    generato = datetime.datetime.fromisoformat(d['generato'])
    eta = (datetime.datetime.now(ROMA) - generato).total_seconds()
    if eta > 3600:
        guasto('file generato %d minuti fa: troppo vecchio' % (eta / 60))
    if eta < -300:
        guasto('file datato nel futuro: orologio sbagliato?')

    # Un file appena scritto puo' comunque contenere risposte vecchie: basta
    # ricostruirlo da pagine lette ore prima. Qui conta quando La Scatola ha
    # davvero sincronizzato le prenotazioni, non quando il file e' nato.
    tempi = [f.get('last_success_at') for f in (d.get('freschezza') or [])
             if f.get('resource') == 'lodging_reservation' and f.get('last_success_at')]
    if not tempi:
        guasto('nessuna informazione di freschezza da La Scatola')
    piu_recente = max(datetime.datetime.fromisoformat(t.replace('Z', '+00:00')) for t in tempi)
    eta_dati = (datetime.datetime.now(datetime.timezone.utc) - piu_recente).total_seconds()
    if eta_dati > 3 * 3600:
        guasto('dati di La Scatola vecchi di %d ore: pagine lette troppo tempo fa'
               % (eta_dati / 3600))

    # Decifra e controlla il contenuto.
    e = d['dati']
    key = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32,
                     salt=base64.b64decode(e['salt']),
                     iterations=e['iter']).derive(chiave.encode())
    try:
        chiaro = AESGCM(key).decrypt(base64.b64decode(e['iv']),
                                     base64.b64decode(e['ct']),
                                     generato.date().isoformat().encode())
    except Exception as err:
        guasto('non si decifra con questa chiave (%s)' % type(err).__name__)
    dati = json.loads(chiaro.decode())

    strutture = dati.get('strutture') or {}
    if not strutture:
        guasto('nessuna struttura nel file')

    totale, oggi = 0, datetime.datetime.now(ROMA).date().isoformat()
    righe_oggi = 0
    for nome, s in strutture.items():
        for x in s.get('soggiorni') or []:
            totale += 1
            if not UUID.fullmatch(x.get('resId', '')):
                guasto('%s: reservation_id non valido %r' % (nome, x.get('resId')))
            if not (x.get('cin') and x.get('cout')) or x['cin'] >= x['cout']:
                guasto('%s: date incoerenti su camera %r' % (nome, x.get('rn')))
            if x.get('stato') not in STATI:
                guasto('%s: stato sconosciuto %r' % (nome, x.get('stato')))
            if x['cin'] == oggi or x['cout'] == oggi or x['cin'] < oggi < x['cout']:
                righe_oggi += 1

    if totale < minimo:
        guasto('solo %d soggiorni, meno del minimo richiesto (%d)' % (totale, minimo))
    if righe_oggi == 0:
        guasto('nessun movimento per oggi: elenco sospetto')

    print('verifica OK: %d soggiorni, %d movimenti oggi, file di %d minuti fa'
          % (totale, righe_oggi, eta / 60))


if __name__ == '__main__':
    main()
