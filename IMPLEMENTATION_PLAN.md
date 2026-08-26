# Vertretungsplan-Monitor für Discord

## Ziel

Der Bot überwacht die offiziellen Mobil-XML-Dateien montags bis freitags von
06:30 bis 15:00 Uhr im Minutentakt. Er prüft die nächsten zehn Schultage,
filtert die persönlichen Profile Luca, Jasper und 8G und meldet neue,
geänderte sowie aufgehobene Vertretungen im vorhandenen Discord-Kanal.

## Umsetzung

1. Die Mobil-XMLs über HTTP Basic Auth abrufen. Vor einem Download werden
   `ETag`, `Last-Modified` und Dateigröße per `HEAD` verglichen.
2. Unterricht über die stabile `UeNr` identifizieren. Kurskürzel und
   ursprüngliche Lehrkraft werden exakt und groß-/kleinschreibungssensitiv
   abgeglichen.
3. Ausfälle, Selbststudium, Vertretungen, Verlegungen und Raumänderungen
   erkennen, Doppelstunden bündeln und Hinweise/Klausuren übernehmen.
4. Beobachtete und bereits gesendete Ereignisse atomar persistieren, damit
   Neustarts und Discord-Fehler keine Duplikate oder verlorenen Meldungen
   erzeugen.
5. Aussagekräftige Discord-Embeds, einen optionalen Überblick um 07:00 Uhr
   und die bestehenden Planbefehle mit Profilauswahl bereitstellen.
6. Runtime-Zustand aus Git entfernen, `.env.example` und README aktualisieren
   und alles durch Fixtures sowie einen sendefreien Live-DRY_RUN prüfen.

## Abnahme

- Der echte 8G-Freitagsfall wird als Block 1 mit dem Ausfall von `8eth7`
  erkannt.
- `CHE1/che1`, `MAT1/mat1`, `ENG1/eng1` und `DEU1/deu1` bleiben getrennt.
- Unveränderte Pläne und Neustarts erzeugen keine Wiederholungen.
- Das Zeitfenster ist `[06:30, 15:00)` in `Europe/Berlin`.
- Ohne Discord-Zugangsdaten kann der vollständige Abruf als `DRY_RUN`
  ausgeführt werden.
