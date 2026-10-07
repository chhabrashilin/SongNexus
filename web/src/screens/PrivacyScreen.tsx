/** Privacy: what we store, what we don't, and the controls you have. */
import {usePageTitle} from '../app/Shell';
import {useI18n} from '../i18n/i18n';

export default function PrivacyScreen() {
  const {t} = useI18n();
  usePageTitle(t('privacy.title'));
  // Long-form copy is English-only in R1; it moves into the message catalog with R2 locales.
  return (
    <article className="stack" lang="en" style={{maxInlineSize: '70ch'}}>
      <h1>{t('privacy.title')}</h1>
      <p>
        You can use SongNexus without an account. Nothing you search or explore
        is tied to you.
      </p>
      <h2>If you sign in</h2>
      <ul>
        <li>
          Google confirms who you are. We keep only an anonymous account ID, not
          your name or email address.
        </li>
        <li>
          We store what you choose to save: hidden artists, your Top 5 (private)
          and settings.
        </li>
        <li>
          Your session is a secure cookie that pages can’t read. You can sign
          out on every device at once.
        </li>
      </ul>
      <h2>On this device</h2>
      <ul>
        <li>
          “Recently viewed” artists and your theme are stored only in this
          browser. Clearing your browser data removes them.
        </li>
      </ul>
      <h2>Your controls</h2>
      <ul>
        <li>
          Download everything we store about you, from You → Download my data.
        </li>
        <li>
          Delete your account from You → Delete account. Your data is removed
          immediately and gone from our systems within 30 days.
        </li>
      </ul>
      <h2>What we never do</h2>
      <ul>
        <li>Sell or share your data, or show ads.</li>
        <li>Keep what you search for: it stays out of our logs.</li>
        <li>Upload your listening files: imports are read on your device.</li>
      </ul>
    </article>
  );
}
