// Retain LABRIX presentation for legacy RTU defaults; honor explicit Owner values.
export function brandTitle(config){const name=config?.brand?.name?.trim();return !name||/^RTU\s*WASH$/i.test(name)?'LABRIX WASH':name}
export function brandSubtitle(config,fallback){const value=config?.brand?.productLine?.trim();return !value||value==='Wash Control'?fallback:value}
export function defaultLanguage(config){return ['uz','ru','kz','ky'].includes(config?.layout?.defaultLanguage)?config.layout.defaultLanguage:'uz'}
