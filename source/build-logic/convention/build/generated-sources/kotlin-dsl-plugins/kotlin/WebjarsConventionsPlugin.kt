/**
 * Precompiled [webjars-conventions.gradle.kts][Webjars_conventions_gradle] script plugin.
 *
 * @see Webjars_conventions_gradle
 */
public
class WebjarsConventionsPlugin : org.gradle.api.Plugin<org.gradle.api.Project> {
    override fun apply(target: org.gradle.api.Project) {
        try {
            Class
                .forName("Webjars_conventions_gradle")
                .getDeclaredConstructor(org.gradle.api.Project::class.java, org.gradle.api.Project::class.java)
                .newInstance(target, target)
        } catch (e: java.lang.reflect.InvocationTargetException) {
            throw e.targetException
        }
    }
}
