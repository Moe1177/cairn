export const charge = (body: string) => fetch('https://api.stripe.com/v1/charges', { method: 'POST', body });
export const ping = () => fetch('/health');
