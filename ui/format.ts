export function money(value: number, currency = 'USD', language = 'en') {
  return new Intl.NumberFormat(language === 'ar' ? 'ar-LB' : 'en-US', {
    style: 'currency', currency, maximumFractionDigits: currency === 'LBP' ? 0 : 2,
  }).format(value);
}
