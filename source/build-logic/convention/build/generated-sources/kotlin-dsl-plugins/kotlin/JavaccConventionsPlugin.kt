/**
 * Precompiled [javacc-conventions.gradle.kts][Javacc_conventions_gradle] script plugin.
 *
 * @see Javacc_conventions_gradle
 */
public
class JavaccConventionsPlugin : org.gradle.api.Plugin<org.gradle.api.Project> {
    override fun apply(target: org.gradle.api.Project) {
        try {
            Class
                .forName("Javacc_conventions_gradle")
                .getDeclaredConstructor(org.gradle.api.Project::class.java, org.gradle.api.Project::class.java)
                .newInstance(target, target)
        } catch (e: java.lang.reflect.InvocationTargetException) {
            throw e.targetException
        }
    }
}
