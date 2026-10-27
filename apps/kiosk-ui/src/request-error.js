// Keep technical response bodies out of user-facing setup errors.
export function requestErrorText(error, language='ru') {
  const pick=(ru,uz,en)=>({ru,uz,en}[language]||ru)
  const status=Number(error?.status)||Number(String(error?.message||error).match(/^HTTP (\d+)$/)?.[1])
  if(status>=500)return pick('Служба поста временно недоступна. Дождитесь восстановления связи и обновите состояние.','Post xizmati vaqtincha mavjud emas. Aloqa tiklanishini kuting va holatni yangilang.','The station service is temporarily unavailable. Wait for reconnection, then refresh the status.')
  if(status===401||status===403)return pick('Доступ не подтверждён. Обновите страницу и войдите снова.','Kirish tasdiqlanmadi. Sahifani yangilang va qayta kiring.','Access was not confirmed. Refresh the page and sign in again.')
  if(status===409)return pick('Действие сейчас недоступно. Проверьте состояние поста и незавершённые операции.','Hozir amalni bajarib bo‘lmaydi. Post holatini va tugallanmagan amallarni tekshiring.','This action is currently unavailable. Check the station state and unfinished operations.')
  if(status)return pick('Не удалось выполнить запрос. Проверьте введённые данные и обновите состояние.','So‘rov bajarilmadi. Kiritilgan ma’lumotlarni tekshiring va holatni yangilang.','The request could not be completed. Check the entered data and refresh the status.')
  if(error?.name==='TypeError'||error?.name==='TimeoutError'||error?.name==='AbortError')return pick('Нет ответа от поста. Проверьте соединение и повторите проверку.','Post javob bermayapti. Ulanishni tekshiring va qayta tekshiring.','The station did not respond. Check the connection and retry the check.')
  return error?.message||String(error||'')
}
