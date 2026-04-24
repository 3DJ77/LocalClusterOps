/**
 * Loads theme configuration from environment variables
 * @returns {import('@librechat/client').IThemeRGB | undefined}
 */
export function getThemeFromEnv() {
  const vsCodiumTheme = {
    'rgb-text-primary': '219 233 255',
    'rgb-text-secondary': '159 180 212',
    'rgb-text-secondary-alt': '129 152 187',
    'rgb-text-tertiary': '104 127 159',
    'rgb-text-warning': '244 212 118',
    'rgb-ring-primary': '116 173 255',
    'rgb-header-primary': '6 29 66',
    'rgb-header-hover': '9 42 90',
    'rgb-header-button-hover': '13 53 107',
    'rgb-surface-active': '18 60 116',
    'rgb-surface-active-alt': '22 74 138',
    'rgb-surface-hover': '18 60 116',
    'rgb-surface-hover-alt': '23 72 127',
    'rgb-surface-primary': '6 29 66',
    'rgb-surface-primary-alt': '3 23 51',
    'rgb-surface-primary-contrast': '0 18 37',
    'rgb-surface-secondary': '9 42 90',
    'rgb-surface-secondary-alt': '13 53 107',
    'rgb-surface-tertiary': '18 60 116',
    'rgb-surface-tertiary-alt': '23 72 127',
    'rgb-surface-dialog': '6 29 66',
    'rgb-surface-submit': '47 127 255',
    'rgb-surface-submit-hover': '116 173 255',
    'rgb-surface-destructive': '110 42 45',
    'rgb-surface-destructive-hover': '136 52 56',
    'rgb-surface-chat': '6 36 81',
    'rgb-border-light': '27 55 102',
    'rgb-border-medium': '39 75 125',
    'rgb-border-medium-alt': '49 90 145',
    'rgb-border-heavy': '59 111 179',
    'rgb-border-xheavy': '119 168 247',
    'rgb-brand-purple': '116 173 255',
    'rgb-presentation': '0 25 51',
    'rgb-background': '0 25 51',
    'rgb-foreground': '219 233 255',
    'rgb-primary': '47 127 255',
    'rgb-primary-foreground': '255 255 255',
    'rgb-secondary': '9 42 90',
    'rgb-secondary-foreground': '219 233 255',
    'rgb-muted': '6 29 66',
    'rgb-muted-foreground': '159 180 212',
    'rgb-accent': '13 53 107',
    'rgb-accent-foreground': '245 249 255',
    'rgb-destructive-foreground': '255 236 236',
    'rgb-border': '39 75 125',
    'rgb-input': '39 75 125',
    'rgb-ring': '116 173 255',
    'rgb-card': '6 29 66',
    'rgb-card-foreground': '219 233 255',
  };

  // Check if any theme environment variables are set
  const hasThemeEnvVars = Object.keys(process.env).some((key) =>
    key.startsWith('REACT_APP_THEME_'),
  );

  if (!hasThemeEnvVars) {
    return vsCodiumTheme;
  }

  // Build theme object from environment variables
  const theme = {};

  // Helper to get env value with prefix
  const getEnv = (key) => process.env[`REACT_APP_THEME_${key}`];

  // Text colors
  if (getEnv('TEXT_PRIMARY')) theme['rgb-text-primary'] = getEnv('TEXT_PRIMARY');
  if (getEnv('TEXT_SECONDARY')) theme['rgb-text-secondary'] = getEnv('TEXT_SECONDARY');
  if (getEnv('TEXT_TERTIARY')) theme['rgb-text-tertiary'] = getEnv('TEXT_TERTIARY');
  if (getEnv('TEXT_WARNING')) theme['rgb-text-warning'] = getEnv('TEXT_WARNING');

  // Surface colors
  if (getEnv('SURFACE_PRIMARY')) theme['rgb-surface-primary'] = getEnv('SURFACE_PRIMARY');
  if (getEnv('SURFACE_SECONDARY')) theme['rgb-surface-secondary'] = getEnv('SURFACE_SECONDARY');
  if (getEnv('SURFACE_TERTIARY')) theme['rgb-surface-tertiary'] = getEnv('SURFACE_TERTIARY');
  if (getEnv('SURFACE_SUBMIT')) theme['rgb-surface-submit'] = getEnv('SURFACE_SUBMIT');
  if (getEnv('SURFACE_SUBMIT_HOVER'))
    theme['rgb-surface-submit-hover'] = getEnv('SURFACE_SUBMIT_HOVER');
  if (getEnv('SURFACE_DESTRUCTIVE'))
    theme['rgb-surface-destructive'] = getEnv('SURFACE_DESTRUCTIVE');
  if (getEnv('SURFACE_DESTRUCTIVE_HOVER'))
    theme['rgb-surface-destructive-hover'] = getEnv('SURFACE_DESTRUCTIVE_HOVER');
  if (getEnv('SURFACE_DIALOG')) theme['rgb-surface-dialog'] = getEnv('SURFACE_DIALOG');
  if (getEnv('SURFACE_CHAT')) theme['rgb-surface-chat'] = getEnv('SURFACE_CHAT');

  // Border colors
  if (getEnv('BORDER_LIGHT')) theme['rgb-border-light'] = getEnv('BORDER_LIGHT');
  if (getEnv('BORDER_MEDIUM')) theme['rgb-border-medium'] = getEnv('BORDER_MEDIUM');
  if (getEnv('BORDER_HEAVY')) theme['rgb-border-heavy'] = getEnv('BORDER_HEAVY');
  if (getEnv('BORDER_XHEAVY')) theme['rgb-border-xheavy'] = getEnv('BORDER_XHEAVY');

  // Brand colors
  if (getEnv('BRAND_PURPLE')) theme['rgb-brand-purple'] = getEnv('BRAND_PURPLE');

  // Header colors
  if (getEnv('HEADER_PRIMARY')) theme['rgb-header-primary'] = getEnv('HEADER_PRIMARY');
  if (getEnv('HEADER_HOVER')) theme['rgb-header-hover'] = getEnv('HEADER_HOVER');

  // Presentation
  if (getEnv('PRESENTATION')) theme['rgb-presentation'] = getEnv('PRESENTATION');

  return Object.keys(theme).length > 0 ? { ...vsCodiumTheme, ...theme } : vsCodiumTheme;
}
