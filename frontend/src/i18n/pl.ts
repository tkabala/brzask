import type { Resources } from './en'

export const pl: Resources = {
  app: {
    name: 'brzask',
    nav: { today: 'Dziś' },
    language: 'Język',
    logout: 'Wyloguj',
  },
  login: {
    title: 'Logowanie',
    password: 'Hasło',
    submit: 'Zaloguj',
    submitting: 'Logowanie…',
    required: 'Wpisz hasło.',
    wrong: 'Złe hasło.',
    locked: 'Za dużo złych haseł. Spróbuj ponownie za {{minutes}} min.',
  },
  proxy: {
    title: 'Zaloguj się przez proxy',
    body: 'Ten serwer bierze użytkownika z reverse proxy przed nim. Otwórz brzask przez to proxy i zaloguj się tam.',
  },
  today: {
    title: 'Dziś',
    empty: 'Dzisiejszego przeglądu jeszcze nie ma.',
    emptyHint: 'Powstaje co rano; do tego czasu nie ma nic do czytania.',
  },
  problem: {
    title: 'Coś poszło nie tak',
    offline: 'Nie można połączyć się z serwerem. Sprawdź, czy działa.',
    retry: 'Spróbuj ponownie',
  },
}
