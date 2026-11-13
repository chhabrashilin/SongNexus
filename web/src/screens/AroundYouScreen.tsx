/** Privacy-first selector for future place and community aggregate data. */
import {useState} from 'react';

import {usePageTitle} from '../app/Shell';
import {Icon} from '../components/Icon';
import {useI18n} from '../i18n/i18n';

type LocationKind = 'state' | 'city' | 'country';
type CommunityKind = 'university' | 'school' | 'workplace';

export function AroundYouScreen() {
  const {t} = useI18n();
  const [locationKind, setLocationKind] = useState<LocationKind>('city');
  const [communityKind, setCommunityKind] =
    useState<CommunityKind>('university');
  const [location, setLocation] = useState('');
  const [community, setCommunity] = useState('');
  const [submitted, setSubmitted] = useState(false);
  usePageTitle(t('around.title'));
  const locationLabel = t(`around.location.${locationKind}`);
  const communityLabel = t(`around.community.${communityKind}`);

  function applySelection() {
    if (location.trim() || community.trim()) setSubmitted(true);
  }

  return (
    <div className="stack product-screen">
      <section className="product-hero stack">
        <span className="product-hero__icon" aria-hidden="true">
          <Icon name="place" />
        </span>
        <p className="product-hero__label">{t('nav.aroundYou')}</p>
        <h1>{t('around.title')}</h1>
        <p className="muted">{t('around.lead')}</p>
      </section>

      <section className="around-form card" aria-label={t('around.title')}>
        <div className="around-form__field">
          <label htmlFor="around-location-kind">
            {t('around.location.label')}
          </label>
          <select
            id="around-location-kind"
            value={locationKind}
            onChange={event => {
              setLocationKind(event.target.value as LocationKind);
              setSubmitted(false);
            }}
          >
            <option value="state">{t('around.location.state')}</option>
            <option value="city">{t('around.location.city')}</option>
            <option value="country">{t('around.location.country')}</option>
          </select>
          <input
            value={location}
            onChange={event => {
              setLocation(event.target.value);
              setSubmitted(false);
            }}
            placeholder={t('around.location.placeholder')}
            aria-label={locationLabel}
          />
        </div>
        <div className="around-form__field">
          <label htmlFor="around-community-kind">
            {t('around.community.label')}
          </label>
          <select
            id="around-community-kind"
            value={communityKind}
            onChange={event => {
              setCommunityKind(event.target.value as CommunityKind);
              setSubmitted(false);
            }}
          >
            <option value="university">
              {t('around.community.university')}
            </option>
            <option value="school">{t('around.community.school')}</option>
            <option value="workplace">{t('around.community.workplace')}</option>
          </select>
          <input
            value={community}
            onChange={event => {
              setCommunity(event.target.value);
              setSubmitted(false);
            }}
            placeholder={t('around.community.placeholder')}
            aria-label={communityLabel}
          />
        </div>
        <button
          className="btn btn--filled"
          type="button"
          disabled={!location.trim() && !community.trim()}
          onClick={applySelection}
        >
          {t('around.apply')}
        </button>
      </section>

      <section className="around-panel card" aria-live="polite">
        <h2>{t('around.selection')}</h2>
        {submitted && (
          <p className="around-selection">
            {location.trim() && `${locationLabel}: ${location.trim()}`}
            {location.trim() && community.trim() && ' · '}
            {community.trim() && `${communityLabel}: ${community.trim()}`}
          </p>
        )}
        <p className="muted">{t('around.empty')}</p>
      </section>

      <section className="privacy-panel card">
        <span className="privacy-panel__icon" aria-hidden="true">
          <Icon name="block" />
        </span>
        <div className="stack">
          <h2>{t('around.privacy.title')}</h2>
          <p className="muted">{t('around.privacy.body')}</p>
        </div>
      </section>
    </div>
  );
}

export default AroundYouScreen;
