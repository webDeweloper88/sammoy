// Presentation catalog. IDs are relay identities, not editable fragrance names.
export const dryFogIds=['aroma_1','aroma_2','aroma_3','aroma_4','aroma_5','blackening','tank_air']
export const dryFogAdditional=['blackening','tank_air']
const names=['SHEIKH SULTAN','BLACK ICE','NARCOTIC','INVICTUS CREED','ANTI-TOBACCO']
export const dryFogLabels={...Object.fromEntries(names.map((name,i)=>['aroma_'+(i+1),[name,name,name,name]])),blackening:['SHINA QORAYTIRISH','ШИНАНЫ ҚАРАЙТУ','ДӨҢГӨЛӨКТҮ КАРАЙТУУ','ЧЕРНЕНИЕ ШИН'],tank_air:['SHINANI DAMLASH','ШИНАҒА АУА ҮРЛЕУ','ДӨҢГӨЛӨККӨ АБА ҮЙЛӨӨ','ПОДКАЧКА ШИН']}
export const dryFogDescriptions={...Object.fromEntries(names.map((_,i)=>['aroma_'+(i+1),['Salon uchun ifor','Салонға арналған хош иіс','Салон үчүн жыт','Аромат для салона']])),blackening:['Shinalarga parvarish','Шина күтімі','Дөңгөлөккө кам көрүү','Уход за шинами'],tank_air:['Shinalarga havo berish','Шинаға ауа беру','Дөңгөлөккө аба берүү','Подача воздуха в шины']}
export const dryFogTones={aroma_1:'#a66b14',aroma_2:'#0088b9',aroma_3:'#be4581',aroma_4:'#197c9b',aroma_5:'#398343',blackening:'#617387',tank_air:'#1978a4'}
export const dryFogTexts={
 uz:{card:'Mijoz kartasi',descriptor:'Salon va shinalarga xizmat',trigger:'Xizmatni tanlang',choose:'Xizmatni tanlang',aromaHeading:'AROMATNI TANLANG',optional:'QO‘SHIMCHA XIZMATLAR',running:'Xizmat davom etmoqda',operatingShort:'Xizmat davom etmoqda',beginTitle:'Xizmatni boshlash',readyToWash:'Xizmatdan foydalanishga tayyormisiz?',recovered:'Balans tiklandi. Xizmatni tanlang.'},
 ru:{card:'Карта клиента',descriptor:'Уход за салоном и шинами',trigger:'Выберите услугу',choose:'Выберите услугу',aromaHeading:'ВЫБЕРИТЕ АРОМАТ',optional:'ДОПОЛНИТЕЛЬНЫЕ УСЛУГИ',running:'Услуга выполняется',operatingShort:'Услуга выполняется',beginTitle:'Начать обслуживание',readyToWash:'Готовы воспользоваться услугой?',recovered:'Баланс восстановлен. Выберите услугу.'},
 kz:{card:'Клиент картасы',descriptor:'Салон мен шина күтімі',trigger:'Қызметті таңдаңыз',choose:'Қызметті таңдаңыз',aromaHeading:'ХОШ ИІСТІ ТАҢДАҢЫЗ',optional:'ҚОСЫМША ҚЫЗМЕТТЕР',running:'Қызмет орындалуда',operatingShort:'Қызмет орындалуда',beginTitle:'Қызметті бастау',readyToWash:'Қызметті пайдалануға дайынсыз ба?'},
 ky:{card:'Кардар картасы',descriptor:'Салон жана дөңгөлөккө кам көрүү',trigger:'Кызматты тандаңыз',choose:'Кызматты тандаңыз',aromaHeading:'ЖЫТТЫ ТАНДАҢЫЗ',optional:'КОШУМЧА КЫЗМАТТАР',running:'Кызмат аткарылууда',operatingShort:'Кызмат аткарылууда',beginTitle:'Кызматты баштоо',readyToWash:'Кызматтан пайдаланууга даярсызбы?'}
}
