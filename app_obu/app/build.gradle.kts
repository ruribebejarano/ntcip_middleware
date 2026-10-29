plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("org.jetbrains.kotlin.plugin.serialization")
}

android {
    namespace = "pe.pucp.ntcip.obu"
    // compileSdk 37: lo que exigen las versiones estables actuales de
    // androidx (ver AAR metadata al compilar). Independiente de
    // targetSdk/minSdk -- controla solo contra qué APIs se compila, no el
    // comportamiento en tiempo de ejecución (targetSdk sigue en 34,
    // minSdk en 29, como se acordó).
    compileSdk = 37

    defaultConfig {
        applicationId = "pe.pucp.ntcip.obu"
        minSdk = 29
        targetSdk = 34
        versionCode = 1
        versionName = "0.1-etapa1"

        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    buildFeatures {
        viewBinding = true
    }

    // HiveMQ MQTT Client arrastra varios jars de Netty que repiten el mismo
    // META-INF/INDEX.LIST (y io.netty.versions.properties): no aportan nada
    // en tiempo de ejecucion, solo hay que evitar que choquen al empaquetar.
    packaging {
        resources {
            excludes += setOf(
                "META-INF/INDEX.LIST",
                "META-INF/io.netty.versions.properties",
            )
        }
    }
}

kotlin {
    compilerOptions {
        jvmTarget.set(org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17)
    }
}

dependencies {
    implementation("androidx.core:core-ktx:1.19.1")
    implementation("androidx.appcompat:appcompat:1.8.0")
    implementation("com.google.android.material:material:1.14.0")
    implementation("androidx.lifecycle:lifecycle-service:2.11.0")
    implementation("androidx.lifecycle:lifecycle-runtime-ktx:2.11.0")
    implementation("androidx.activity:activity-ktx:1.13.0")

    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.11.0")
    implementation("org.jetbrains.kotlinx:kotlinx-serialization-json:1.12.0")

    // Cliente MQTT 5, el mismo protocolo que gateway/obu_emulada.py (paho-mqtt en Python).
    implementation("com.hivemq:hivemq-mqtt-client:1.4.1")

    // Mapa OSM (osmdroid), ver docs/CONTRATO_OBU.md ("mapa con ruta obligatorio").
    implementation("org.osmdroid:osmdroid-android:6.1.20")

    testImplementation("junit:junit:4.13.2")
    testImplementation("org.jetbrains.kotlinx:kotlinx-coroutines-test:1.11.0")
}
