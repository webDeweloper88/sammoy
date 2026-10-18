const fogFiles={aroma_1:'sheikh_sultan',aroma_2:'black_ice',aroma_3:'narcotic',aroma_4:'invictus_creed',aroma_5:'anti_tobacco',blackening:'blackening',tank_air:'tank_air'}
const files={water:'water',foam:'foam',wax:'wax',chem:'chemical',osmos:'osmosis',nano:'nano',air:'air',vacuum:'vacuum'}
export const modePhoto=id=>fogFiles[id]?`/assets/dry-fog/${fogFiles[id]}.webp`:files[id]?`/assets/theme2/modes-v2/${files[id]}.webp`:null
