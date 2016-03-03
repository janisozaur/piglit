<%inherit file="execution_base.mako"/>
[vertex shader]
<%include file="base-inversions.vert.mako"/>
[fragment shader]
#version 150

in vec4 fs_color;
out vec4 color;

void main()
{
    color = fs_color;
}
