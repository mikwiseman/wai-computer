package `is`.waiwai.say.data

sealed class ApiError(message: String, cause: Throwable? = null) : Exception(message, cause) {
    class InvalidUrl(path: String) : ApiError("Invalid URL for path: $path")

    class Http(
        val statusCode: Int,
        val detail: String?,
    ) : ApiError(detail ?: "Server error ($statusCode)")

    class Network(cause: Throwable) : ApiError(cause.message ?: "Network error", cause)

    class Serialization(cause: Throwable) : ApiError(
        cause.message ?: "Failed to parse server response",
        cause,
    )

    data object Unauthorized : ApiError("Session expired. Please sign in again.")
}
