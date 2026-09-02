import { MiddlewareConsumer, Module, NestModule } from "@nestjs/common";
import { AuthContextMiddleware } from "./auth-context.middleware";
import { SecurityHeadersMiddleware } from "./security-headers.middleware";
@Module({})
export class SecurityModule implements NestModule{configure(consumer:MiddlewareConsumer){consumer.apply(SecurityHeadersMiddleware,AuthContextMiddleware).forRoutes("*");}}
