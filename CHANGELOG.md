# Changelog

## 0.2.0

- Natywne zdarzenia Home Assistant po ukończeniu pliku i opróżnieniu kolejki.
- Deduplikacja zakończeń oraz odtwarzanie pominiętych zdarzeń z historii po reconnect SSE.
- Przykład automatyzacji Companion App z powiadomieniem i synchronizacją filesystem Music Assistant.
- Automatyczne tworzenie GitHub Release po wypchnięciu zgodnego taga SemVer.
- Blokada wydania, gdy wersja taga i `manifest.json` nie są zgodne.

## 0.1.0

- Supervisor discovery z potwierdzeniem i bez ręcznego podawania tokenu.
- Automatyczna aktualizacja hosta, portu i tokenu przy ponownym wykryciu.
- Akcje `download` i `download_batch` z selektorami oraz lokalizacją EN/PL.
- Sensory kolejki, stanu i postępu aktualizowane przez REST i SSE.
- Lokalny branding aplikacji dla Home Assistant 2026.7.
