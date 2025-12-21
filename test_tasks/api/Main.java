import java.util.*;

public class Main {
    public static void main(String[] args) {
        System.out.println("Java API Server starting...");

        // Simple mock API endpoints
        Map<String, String> endpoints = new HashMap<>();
        endpoints.put("/api/users", "GET - List all users");
        endpoints.put("/api/tasks", "POST - Create new task");
        endpoints.put("/api/health", "GET - Health check");

        System.out.println("Available endpoints:");
        endpoints.forEach((path, method) ->
            System.out.println(method + " " + path)
        );
    }
}