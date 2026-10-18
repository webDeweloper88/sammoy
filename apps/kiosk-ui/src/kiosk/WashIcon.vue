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
const scent='M24 10h16v9H24Z M20 22h24l5 33H15Z M32 2v5 M48 8l5-4 M51 18h8'
for(const id of ['aroma_1','aroma_2','aroma_3','aroma_4','aroma_5'])paths[id]=scent
paths.blackening='M32 5a20 27 0 1 0 0 54a20 27 0 0 0 0-54 M32 14a11 18 0 1 0 0 36a11 18 0 0 0 0-36 M12 15l8 4 M9 30h9 M12 45l8-4 M44 15l8 4 M46 30h9 M44 45l8-4'
paths.tank_air='M26 5a17 26 0 1 0 0 52a17 26 0 0 0 0-52 M26 15a8 16 0 1 0 0 32a8 16 0 0 0 0-32 M36 35h13v13h11 M49 35V23h10'
</script>
<template><svg :data-icon="name" viewBox="0 0 64 64" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><template v-if="name==='pause'"><rect x="18" y="13" width="10" height="38" rx="3" fill="currentColor" stroke="none"/><rect x="36" y="13" width="10" height="38" rx="3" fill="currentColor" stroke="none"/></template><path v-else-if="name==='play'" d="M24 13 51 30a2.4 2.4 0 0 1 0 4L24 51a2.4 2.4 0 0 1-4-2V15a2.4 2.4 0 0 1 4-2Z" fill="currentColor" stroke="none"/><rect v-else-if="name==='stop'" x="15" y="15" width="34" height="34" rx="4" fill="currentColor" stroke="none"/><path v-else :d="paths[name] || paths.water" /></svg></template>
