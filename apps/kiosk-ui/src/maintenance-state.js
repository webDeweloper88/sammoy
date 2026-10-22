import {ref} from 'vue'
// Keep the progress screen alive while reset intentionally revokes auth.
export const maintenanceActive=ref(false)
