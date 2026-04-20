import { useTranslation } from '@autoservice/i18n';

/**
 * Rendered when the operator console is loaded without a tenant context
 * (e.g. `/`, `/operator`, unknown path). Rather than crashing while trying
 * to open a WS connection with an empty tenant, we surface a short message
 * and an example URL so the operator can navigate to the right tenant.
 */
export function NoTenantFallback() {
  const { t } = useTranslation();
  return (
    <div
      data-testid="no-tenant-fallback"
      className="op-no-tenant"
      style={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        minHeight: '100vh',
        padding: '2rem',
        textAlign: 'center',
        gap: '0.75rem',
      }}
    >
      <h2>{t('operator.no_tenant.title', { defaultValue: 'Select a tenant' })}</h2>
      <p>
        {t('operator.no_tenant.hint', {
          defaultValue:
            'Open this console with a tenant path, e.g. /t/<your-tenant>/operator',
        })}
      </p>
      <code data-testid="no-tenant-example">/t/&lt;your-tenant&gt;/operator</code>
    </div>
  );
}
