<p align="center">
  <img src="https://raw.githubusercontent.com/Misiu/yt_dlp-integration/main/custom_components/youtube_audio_downloader/brand/logo.png" alt="YouTube Audio Downloader" width="420">
</p>

# YouTube Audio Downloader dla Home Assistant

Integracja HACS dla aplikacji [YouTube Audio Downloader](https://github.com/Misiu/yt_dlp-app). Dodaje automatyczne wykrywanie aplikacji, akcje pobierania oraz sensory kolejki i postępu. Komunikacja odbywa się wyłącznie w lokalnej sieci kontenerów Home Assistant przez uwierzytelnione REST API i Server-Sent Events.

> [!IMPORTANT]
> Pobieraj wyłącznie materiały, do których masz prawa lub zgodę właściciela. Użytkownik odpowiada za zgodność użycia z prawem i warunkami serwisu.

## Wymagania

- Home Assistant **2026.7.0 lub nowszy** z Supervisorem i obsługą aplikacji;
- uruchomiona aplikacja YouTube Audio Downloader;
- HACS do zalecanej instalacji integracji.

## Instalacja

### 1. Zainstaluj aplikację

[![Dodaj repozytorium aplikacji do Home Assistant](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2FMisiu%2Fyt_dlp-app)

Zainstaluj i uruchom aplikację **YouTube Audio Downloader**. Nie musisz kopiować żadnego tokenu — aplikacja tworzy go i przekazuje Home Assistantowi przez Supervisor discovery.

### 2. Zainstaluj integrację przez HACS

[![Dodaj do HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=Misiu&repository=yt_dlp-integration&category=integration)

Po pobraniu integracji uruchom ponownie Home Assistant.

### 3. Zatwierdź wykrytą integrację

Uruchomiona aplikacja automatycznie zgłosi usługę `youtube_audio_downloader`. W **Ustawienia → Urządzenia i usługi** pojawi się wykryta integracja. Otwórz ją i zatwierdź konfigurację.

[![Otwórz integracje](https://my.home-assistant.io/badges/integrations.svg)](https://my.home-assistant.io/redirect/integrations/)

Ręczne dodawanie integracji nie prosi o host, port ani token. Te dane są generowane przez aplikację i bezpiecznie aktualizowane przy ponownym wykryciu.

Home Assistant 2026.7 blokuje rediscovery przed uruchomieniem config flow, gdy integracja używa manifestowej flagi `single_config_entry`. Dlatego pojedyncza instancja jest egzekwowana bezpośrednio przez config flow: druga aplikacja jest odrzucana, natomiast ponowne wykrycie tej samej instancji może zaktualizować host, port i token oraz przeładować wpis.

## Encje

Integracja tworzy jedno urządzenie usługi i trzy sensory:

| Sensor | Znaczenie |
|---|---|
| Długość kolejki | Liczba oczekujących zadań |
| Bieżący stan | Stan aplikacji lub aktywnego pobierania |
| Postęp pobierania | Postęp aktywnego zadania w procentach |

Sensory stają się niedostępne po utracie połączenia. Stan początkowy i okresowe uzgadnianie są pobierane przez REST, a bieżące zmiany docierają natychmiast przez SSE. Sensory stanu i postępu udostępniają także bezpieczne atrybuty `job_id`, `title` i `artist`; źródłowy adres filmu nie jest publikowany jako atrybut.

## Akcje

### Pobranie jednego filmu

W edytorze automatyzacji wybierz akcję **YouTube Audio Downloader: Pobierz audio** albo użyj YAML:

```yaml
actions:
  - action: youtube_audio_downloader.download
    data:
      url: "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
```

Obsługiwane są standardowe adresy HTTPS `youtube.com`, YouTube Shorts, adresy osadzone oraz `youtu.be`. Ostateczna walidacja adresu zawsze odbywa się w aplikacji.

### Pobranie paczki

Akcja paczkowa przyjmuje od 1 do 50 adresów. Cała paczka jest walidowana i dodawana atomowo — jeśli choć jeden adres jest błędny, żadne zadanie nie trafi do kolejki.

```yaml
actions:
  - action: youtube_audio_downloader.download_batch
    data:
      urls:
        - "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
        - "https://youtu.be/9bZkp7q19f0"
```

### Skrypt z polem URL

Poniższy skrypt tworzy w interfejsie pole do wklejenia adresu:

```yaml
alias: Pobierz audio z YouTube
mode: queued
fields:
  url:
    name: Adres YouTube
    required: true
    selector:
      text:
        type: url
        autocomplete: url
sequence:
  - action: youtube_audio_downloader.download
    data:
      url: "{{ url }}"
```

### Powiadomienie o rozpoczęciu pobierania

Identyfikatory encji mogą różnić się zależnie od języka i istniejących nazw. Wybierz właściwą encję w edytorze lub dopasuj poniższy przykład:

```yaml
alias: YouTube Audio — rozpoczęto pobieranie
triggers:
  - trigger: state
    entity_id: sensor.youtube_audio_downloader_current_state
    to: downloading
actions:
  - action: persistent_notification.create
    data:
      title: Pobieranie audio
      message: >-
        {{ state_attr('sensor.youtube_audio_downloader_current_state', 'artist') }} —
        {{ state_attr('sensor.youtube_audio_downloader_current_state', 'title') }}
```

## Rozwiązywanie problemów

- **Integracja nie została wykryta:** sprawdź, czy aplikacja jest uruchomiona, zaktualizuj ją i uruchom ponownie. Zgłoszenie discovery jest ponawiane po błędach i raz dziennie.
- **Akcja zgłasza pełną kolejkę lub duplikat:** poczekaj na zakończenie aktywnego zadania albo usuń duplikat z paczki.
- **Encje są niedostępne:** sprawdź log aplikacji i jej stan w panelu aplikacji. Integracja sama ponawia SSE z ograniczonym opóźnieniem wykładniczym.
- **Zmieniła się instalacja aplikacji:** po usunięciu danych aplikacji powstaje nowa tożsamość i token. Usuń starą konfigurację integracji i zatwierdź nowo wykrytą instancję.

Token uwierzytelniający i źródłowe adresy filmów nie są zapisywane w logach integracji.

## Rozwój i wydania

Repozytorium jest walidowane przez Ruff, mypy, pytest, Hassfest i HACS. Wydania dla HACS powinny być publikowane jako GitHub Releases, nie tylko tagi.

Licencja: [MIT](LICENSE).
