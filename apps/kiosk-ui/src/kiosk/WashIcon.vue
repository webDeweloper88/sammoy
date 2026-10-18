<script setup>
defineProps({ name:String })
const paths = {
 water:'M32 5C25 17 14 28 14 40a18 18 0 0 0 36 0C50 28 39 17 32 5Z',
 foam:'M31 8a10 10 0 1 1 16 14 M30 22a16 16 0 1 0-10 28 M35 31a14 14 0 1 0 0 28a14 14 0 0 0 0-28 M44 21a9 9 0 1 1 9 15',
 wax:'m20 5 5 14 13 5-13 5-5 14-5-14L2 24l13-5Z M48 28l4 10 10 4-10 4-4 12-4-12-10-4 10-4Z',
 osmos:'M32 5C25 17 14 28 14 40a18 18 0 0 0 36 0C50 28 39 17 32 5Z M40 37q6 12-7 16',
 chem:'M22 5h20 M25 5v22L11 50q-3 8 6 8h30q9 0 6-8L39 27V5 M19 40h26',
 nano:'m32 3 14 8v16l-14 8-14-8V11Z M18 27 4 35v16l14 8 14-8V35 M46 27l12 7 M47 45a5 5 0 1 0 0 10a5 5 0 0 0 0-10',
 air:'M4 22h33a9 9 0 1 0-9-9 M4 32h47a8 8 0 1 0-8-8 M4 42h31a9 9 0 1 1-9 9',
 vacuum:'M8 56h31l-5-20H16Z M21 36V23a7 7 0 0 1 14 0 M28 29V17a14 14 0 0 1 28 0v38 M50 57h12',
 pause:'M23 14v36 M41 14v36',play:'m23 12 27 20-27 20Z',
 wallet:'M8 17h46v39H8Z M8 17 43 6v11 M40 30h18v14H40Z',cash:'M5 14h54v36H5Z M13 21h3 M48 43h3 M37 24c-13-6-17 8-5 8s8 14-5 8 M32 20v24',
 qr:'M5 5h19v19H5Z M40 5h19v19H40Z M5 40h19v19H5Z M39 39h8v9h12v11H39Z M58 33v4 M31 6v11 M31 28v7 M8 32h13',
 card:'M4 13h43v38H4Z M4 24h43 M12 40h12 M53 22q10 10 0 20 M49 27q5 5 0 10',
 help:'M32 4a28 28 0 1 0 0 56a28 28 0 0 0 0-56 M23 24a9 9 0 1 1 15 7q-6 3-6 10 M32 49v1',
 home:'M5 29 32 6l27 23 M13 25v33h14V40h10v18h14V25',
 clock:'M32 4a28 28 0 1 0 0 56a28 28 0 0 0 0-56 M32 15v18l13 8',
 coins:'M8 15c0-13 48-13 48 0s-48 13-48 0Z M8 15v13c0 13 48 13 48 0V15 M8 29v13c0 13 48 13 48 0V29 M8 43v9c0 13 48 13 48 0v-9',
 close:'M15 15 49 49 M49 15 15 49',phone:'m15 5 12 15-8 8q5 12 17 17l8-8 15 12q-3 12-13 10C24 52 12 40 5 18 3 8 15 5 15 5Z'
}
// One stroke system, distinct silhouettes; symbols identify fragrances without
// claiming their ingredients. Customer labels remain the accessible names.
Object.assign(paths,{
 aroma_1:'M10 20l10 8L32 12l12 16 10-8-5 27H15Z M17 54h30 M23 39h18',
 aroma_2:'M32 6v52 M9 19l46 26 M9 45l46-26 M25 12l7 7 7-7 M25 52l7-7 7 7 M10 28l10-3-2-10 M54 36l-10 3 2 10 M18 49l2-10-10-3 M46 15l-2 10 10 3',
 aroma_3:'M32 32C12 23 13 8 24 10c6 1 8 10 8 22Z M32 32C30 10 43 3 49 12c4 6-3 14-17 20Z M32 32c20-9 32 1 25 11-5 6-15 2-25-11Z M32 32c15 16 9 31-2 27-7-2-7-13 2-27Z M32 32C22 51 6 50 7 38c1-8 12-10 25-6Z',
 aroma_4:'M32 5l21 8v17c0 14-9 23-21 29C20 53 11 44 11 30V13Z M22 32l7 7 14-17',
 aroma_5:'M12 48C3 25 20 9 53 9c1 31-14 49-35 42 M13 55l28-31 M24 43V29 M24 43h14',
 blackening:'M27 8a18 24 0 1 0 0 48a18 24 0 0 0 0-48 M27 17a9 15 0 1 0 0 30a9 15 0 0 0 0-30 M12 19l7 4 M9 32h9 M12 45l7-4 M48 6l3 8 8 3-8 3-3 8-3-8-8-3 8-3Z',
 tank_air:'M23 8a16 24 0 1 0 0 48a16 24 0 0 0 0-48 M23 17a7 15 0 1 0 0 30a7 15 0 0 0 0-30 M39 40h8v12h10 M45 7h14v21H45Z M52 23v-8 M48 15l4-4 4 4'
})
</script>
<template><svg :data-icon="name" viewBox="0 0 64 64" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><template v-if="name==='pause'"><rect x="18" y="13" width="10" height="38" rx="3" fill="currentColor" stroke="none"/><rect x="36" y="13" width="10" height="38" rx="3" fill="currentColor" stroke="none"/></template><path v-else-if="name==='play'" d="M24 13 51 30a2.4 2.4 0 0 1 0 4L24 51a2.4 2.4 0 0 1-4-2V15a2.4 2.4 0 0 1 4-2Z" fill="currentColor" stroke="none"/><rect v-else-if="name==='stop'" x="15" y="15" width="34" height="34" rx="4" fill="currentColor" stroke="none"/><path v-else :d="paths[name] || paths.water" /></svg></template>
