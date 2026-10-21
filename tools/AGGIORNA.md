# Aggiornamento dei dati La Scatola → piattaforma arrivi/partenze

Procedura per l'attività pianificata che riscrive `scatola.json`. La **chiave** per
cifrare NON è in questo repository (è pubblico): viene data nel testo dell'attività.

## Regole

- Gli ID ricevuti da Slope / La Scatola non si modificano mai: si copiano identici.
  `tools/costruisci.py` rifiuta un ID che non abbia la forma di un UUID, proprio per
  far fallire la costruzione se qualcosa è stato trascritto male.
- Il repository è pubblico: i soggiorni si pubblicano solo cifrati. In chiaro restano
  soltanto data di generazione, finestra e freschezza, che servono alla pagina per
  accendere il semaforo prima di decifrare.
- Si pubblica **solo** `scatola.json`. Non toccare `index.html` né `tools/`.
- Se La Scatola non risponde, o `tools/verifica.py` non finisce con `verifica OK`:
  **non pubblicare**. La pagina online continua con l'ultimo file riuscito, e un
  elenco di un'ora fa è meglio di uno sbagliato.

## Dati

- Tre strutture, `property_id` da copiare identici:
  Saslong `33333333-3333-4333-8333-333333333333` ·
  Hartmann `22222222-2222-4222-8222-222222222222` ·
  Acadia `11111111-1111-4111-8111-111111111111`.
- `G` = oggi nel fuso Europe/Rome (AAAA-MM-GG).
- Finestra: soggiorni che toccano i 30 giorni da `G`. Acadia d'autunno è chiusa e
  risulta a zero: è corretto, non è un errore.

## Passi

1. **Lettura**: `query_curated_view` sulla vista `curated_operational_stays` con
   - `property_id in [i tre id]`
   - `departure gte G`
   - `arrival lte G+30`
   - `booking_status neq CANCELLED`
   - `order_by arrival asc`, `limit 500`

   Segui `next_cursor` finché non è nullo. Il sistema salva su file le risposte
   grandi: annota i percorsi, servono al passo 2. **Non ricopiare** i dati a mano.

   Se l'ultima pagina arriva nel messaggio invece che su file, rileggi la stessa
   query con `order_by arrival desc`: la prima pagina in ordine inverso copre la
   coda e di solito finisce su file. Il costruttore scarta i doppioni per
   `reservation_id`, quindi le pagine possono sovrapporsi senza danno.

2. **Intestatari**: `query_curated_view` sulla vista `curated_guest_stays` con
   - `property_id in [i tre id]`
   - `stay_end gte G`
   - `stay_start lte G+30`
   - `is_primary_guest eq true`
   - `order_by stay_start asc`, `limit 500`

   Serve solo il nome dell'intestatario, che la reception usa per riconoscere la
   prenotazione: un numero di stanza da solo non dice a chi si sta cambiando camera.
   Vale lo stesso trucco dell'ordine inverso per la coda. **Attenzione**: Slope ha
   il nome solo per gli ospiti gia' registrati, cioe' in pratica da quando fanno il
   check-in. Le prenotazioni future restano quasi tutte senza nome: e' normale, non
   e' un errore, e il costruttore lo dice nella riga RIEPILOGO.

3. **Costruzione**, dalla cartella del repository:

   ```
   python3 tools/costruisci.py "<CHIAVE>" scatola.json "soggiorni1.txt,soggiorni2.txt,..." "intestatari1.txt,intestatari2.txt,..."
   ```

   Legge le righe `RIEPILOGO` su stderr: il totale deve coincidere con `page.total`.
   Se manca il modulo `cryptography`, installalo con
   `pip install --break-system-packages cryptography`.

4. **Verifica**:

   ```
   python3 tools/verifica.py "<CHIAVE>" scatola.json
   ```

   Deve finire con `verifica OK`. Controlla fra l'altro che i soggiorni non siano
   finiti in chiaro, che ci siano movimenti per oggi e che i dati di La Scatola non
   siano vecchi di più di tre ore — un file appena scritto può comunque contenere
   risposte lette molto prima.

5. **Pubblicazione**: `git add scatola.json`, commit `Dati La Scatola <AAAA-MM-GG HH:MM>`,
   `git push origin HEAD:main`. Poi controlla con `git log origin/main -1` che il
   commit sia arrivato.

   Se il push è rifiutato perché il repository è cambiato nel frattempo, non fare
   rebase né merge: copia `scatola.json` fuori dal repository, `git fetch origin main`,
   `git reset --hard origin/main`, rimetti il file al suo posto, poi di nuovo add,
   commit e push. Una volta sola.

## La chiave

La stessa chiave sta in due posti e deve coincidere:

- nel testo dell'attività pianificata (per cifrare);
- in Firebase, nodo `config/chiaveScatola` (per decifrare dalla pagina, dopo l'accesso).

Se le due divergono, la pagina scrive «I dati non si aprono con la chiave presente».
Per cambiarla: prima aggiorna Firebase, poi il testo dell'attività, poi fai girare
l'attività a mano.
