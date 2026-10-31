<?php
namespace Engine\Host;

interface Adapter
{
    public function cdr(): array;
    public function extensions(): array;
}
