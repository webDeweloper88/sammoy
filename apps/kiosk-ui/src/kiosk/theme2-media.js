const files={water:'water',foam:'foam',wax:'wax',chem:'chemical',osmos:'osmosis',nano:'nano',air:'air',vacuum:'vacuum'}
export const modePhoto=id=>files[id]?`/assets/theme2/modes-v2/${files[id]}.webp`:null
