// Build raíz: solo declara los plugins para que las versiones queden fijas
// en un solo lugar (app/build.gradle.kts los aplica con `id(...)` sin version).
plugins {
    id("com.android.application") version "9.5.0" apply false
    id("org.jetbrains.kotlin.android") version "2.4.21" apply false
    id("org.jetbrains.kotlin.plugin.serialization") version "2.4.21" apply false
}
