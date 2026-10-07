/**
 * Google Sign-In through Firebase Authentication. Imported lazily on the first
 * sign-in, so the Firebase SDK never weighs on the initial page load (plan §23).
 *
 * Configuration comes from VITE_FIREBASE_* variables. For local development
 * set VITE_FIREBASE_AUTH_EMULATOR=http://127.0.0.1:9099.
 */
import {initializeApp, type FirebaseApp} from 'firebase/app';
import {
  connectAuthEmulator,
  getAuth,
  GoogleAuthProvider,
  signInWithPopup,
  signOut,
  type Auth,
} from 'firebase/auth';

let auth: Auth | null = null;

/** Thrown when the VITE_FIREBASE_* configuration is missing. */
export class SignInNotConfiguredError extends Error {
  override name = 'SignInNotConfiguredError';
}

function firebaseAuth(): Auth {
  if (auth) return auth;
  const env = import.meta.env;
  const apiKey = env.VITE_FIREBASE_API_KEY as string | undefined;
  const projectId = env.VITE_FIREBASE_PROJECT_ID as string | undefined;
  if (!apiKey || !projectId) {
    throw new SignInNotConfiguredError('Firebase is not configured');
  }
  const app: FirebaseApp = initializeApp({
    apiKey,
    projectId,
    authDomain:
      (env.VITE_FIREBASE_AUTH_DOMAIN as string | undefined) ??
      `${projectId}.firebaseapp.com`,
  });
  auth = getAuth(app);
  const emulator = env.VITE_FIREBASE_AUTH_EMULATOR as string | undefined;
  if (emulator) connectAuthEmulator(auth, emulator, {disableWarnings: true});
  return auth;
}

/**
 * Runs Google Sign-In and returns a fresh ID token for the server to verify.
 * The Firebase client session is ended right away: the server session is the
 * only session, and no Google tokens linger in browser storage.
 */
export async function getGoogleIdToken(): Promise<string> {
  const instance = firebaseAuth();
  const provider = new GoogleAuthProvider();
  provider.setCustomParameters({prompt: 'select_account'});
  const credential = await signInWithPopup(instance, provider);
  try {
    return await credential.user.getIdToken();
  } finally {
    await signOut(instance);
  }
}
