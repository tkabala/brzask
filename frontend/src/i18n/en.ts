export const en = {
  app: {
    name: 'brzask',
    nav: { today: 'Today' },
    language: 'Language',
    logout: 'Log out',
  },
  login: {
    title: 'Log in',
    password: 'Password',
    submit: 'Log in',
    submitting: 'Logging in…',
    required: 'Enter the password.',
    wrong: 'Wrong password.',
    locked: 'Too many wrong passwords. Try again in {{minutes}} min.',
  },
  proxy: {
    title: 'Sign in through your proxy',
    body: 'This server takes the user from the reverse proxy in front of it. Open brzask through that proxy and sign in there.',
  },
  today: {
    title: 'Today',
    empty: 'No digest yet today.',
    emptyHint: 'It is built each morning; until then there is nothing to read.',
  },
  problem: {
    title: 'Something went wrong',
    offline: 'The server cannot be reached. Check that it is running.',
    retry: 'Try again',
  },
} as const

// Every language has exactly these keys.
type Strings<T> = { [K in keyof T]: T[K] extends string ? string : Strings<T[K]> }
export type Resources = Strings<typeof en>
