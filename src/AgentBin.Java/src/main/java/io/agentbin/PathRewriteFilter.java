package io.agentbin;

import io.quarkus.vertx.web.RouteFilter;
import io.vertx.ext.web.RoutingContext;
import jakarta.enterprise.context.ApplicationScoped;

/**
 * Rewrites /spec (no trailing slash) to /spec/ so Quarkus root-path routing works.
 * The A2A SDK registers POST / which becomes POST /spec/ with root-path=/spec,
 * but clients send POST /spec (no trailing slash).
 */
@ApplicationScoped
public class PathRewriteFilter {

    @RouteFilter(100)
    void rewriteSpecPath(RoutingContext rc) {
        String path = rc.request().path();
        if (path.equals("/spec")) {
            rc.reroute(rc.request().method(), "/spec/");
            return;
        }
        rc.next();
    }
}
